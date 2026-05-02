using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Kinect;

namespace BuddyKinect
{
    class Program
    {
        static KinectSensor sensor;
        static byte[] pixelData;
        static Socket frameSocket;
        static IPEndPoint pythonEndpoint;

        static void Main(string[] args)
        {
            Console.WriteLine("Starting Buddy Kinect Server...");
            
            if (KinectSensor.KinectSensors.Count == 0)
            {
                Console.WriteLine("No Kinect sensors found.");
                return;
            }

            sensor = KinectSensor.KinectSensors[0];
            sensor.ColorStream.Enable(ColorImageFormat.RgbResolution640x480Fps30);
            sensor.DepthStream.Enable(DepthImageFormat.Resolution640x480Fps30);
            sensor.SkeletonStream.Enable();

            pixelData = new byte[sensor.ColorStream.FramePixelDataLength];

            sensor.ColorFrameReady += Sensor_ColorFrameReady;
            
            try
            {
                sensor.Start();
                Console.WriteLine("Kinect started.");
            }
            catch (Exception ex)
            {
                Console.WriteLine("Failed to start Kinect: " + ex.Message);
                return;
            }

            // UDP socket for fast frame streaming
            frameSocket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
            // Increase send buffer size because UDP default is too small for 1.2MB frames
            // Actually UDP max packet is 65507 bytes. We CANNOT send 1.2MB over a single UDP packet!
            // We MUST use TCP for uncompressed frames, or we compress to JPEG.
            // Let's use TCP for frames.
            
            Task.Factory.StartNew(() => StartFrameServer());
            Task.Factory.StartNew(() => StartCommandServer());

            Console.WriteLine("Server running. Press Enter to exit.");
            Console.ReadLine();
        }

        static void StartFrameServer()
        {
            TcpListener listener = new TcpListener(IPAddress.Any, 8002);
            listener.Start();
            Console.WriteLine("Frame server listening on TCP 8002...");

            while (true)
            {
                try
                {
                    TcpClient client = listener.AcceptTcpClient();
                    Console.WriteLine("Python Vision Client connected!");
                    Task.Factory.StartNew(() => HandleFrameClient(client));
                }
                catch (Exception ex) { Console.WriteLine(ex.Message); }
            }
        }

        static TcpClient activeFrameClient;
        static NetworkStream activeFrameStream;
        static object streamLock = new object();

        static void HandleFrameClient(TcpClient client)
        {
            lock (streamLock)
            {
                activeFrameClient = client;
                activeFrameStream = client.GetStream();
            }
        }

        private static void Sensor_ColorFrameReady(object sender, ColorImageFrameReadyEventArgs e)
        {
            using (ColorImageFrame frame = e.OpenColorImageFrame())
            {
                if (frame != null)
                {
                    frame.CopyPixelDataTo(pixelData);
                    
                    lock (streamLock)
                    {
                        if (activeFrameStream != null)
                        {
                            try
                            {
                                // Send length prefix then data
                                byte[] length = BitConverter.GetBytes(pixelData.Length);
                                activeFrameStream.Write(length, 0, 4);
                                activeFrameStream.Write(pixelData, 0, pixelData.Length);
                            }
                            catch
                            {
                                activeFrameStream = null;
                                activeFrameClient = null;
                            }
                        }
                    }
                }
            }
        }

        static void StartCommandServer()
        {
            TcpListener listener = new TcpListener(IPAddress.Any, 8003);
            listener.Start();
            Console.WriteLine("Command server listening on TCP 8003...");

            while (true)
            {
                try
                {
                    TcpClient client = listener.AcceptTcpClient();
                    Task.Factory.StartNew(() => HandleCommandClient(client));
                }
                catch { }
            }
        }

        static void HandleCommandClient(TcpClient client)
        {
            using (var stream = client.GetStream())
            {
                byte[] buffer = new byte[4];
                while (true)
                {
                    try
                    {
                        int read = stream.Read(buffer, 0, 4);
                        if (read == 0) break;
                        
                        int angle = BitConverter.ToInt32(buffer, 0);
                        if (angle >= -27 && angle <= 27)
                        {
                            try
                            {
                                sensor.ElevationAngle = angle;
                            }
                            catch (Exception ex)
                            {
                                Console.WriteLine("Elevation error: " + ex.Message);
                            }
                        }
                    }
                    catch
                    {
                        break;
                    }
                }
            }
        }
    }
}
