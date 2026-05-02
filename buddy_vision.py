import cv2
import numpy as np
import socket
import struct
import time
import json
import httpx
from ultralytics import YOLO
import threading

def run_vision():
    print("Loading YOLO models (FP16)...")
    # Load models. Setting half=True for FP16 optimization.
    # YOLO automatically uses TensorRT if available and exported, otherwise falls back to PyTorch FP16/CUDA.
    try:
        model_pose = YOLO('yolov8n-pose.pt')
        model_obj = YOLO('yolov8n.pt')
        # warmup
        model_pose(np.zeros((480, 640, 3), dtype=np.uint8), device="cpu", verbose=False)
        model_obj(np.zeros((480, 640, 3), dtype=np.uint8), device="cpu", verbose=False)
        print("Models loaded.")
    except Exception as e:
        print(f"Failed to load YOLO: {e}")
        return

    # Frame TCP connection to KinectServer
    frame_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    connected = False
    while not connected:
        try:
            print("Connecting to KinectServer (Frames on 8002, Commands on 8003)...")
            frame_socket.connect(('127.0.0.1', 8002))
            command_socket.connect(('127.0.0.1', 8003))
            connected = True
        except Exception as e:
            print("Waiting for KinectServer...", e)
            time.sleep(2)

    print("Connected to KinectServer!")

    # Current angle state
    current_angle = 0
    last_motor_update = time.time()
    
    def send_tilt(angle):
        try:
            command_socket.sendall(struct.pack('i', angle))
        except:
            pass

    def update_llm_state(state):
        try:
            httpx.post("http://localhost:8001/api/vision_state", json={"state": state}, timeout=1.0)
        except:
            pass

    last_state_json = ""
    latest_frame_lock = threading.Lock()
    latest_frame_jpeg = [None]  # Shared frame for LLM
    
    def frame_save_worker():
        """Periodically save the latest frame to disk for the LLM to consume."""
        import pathlib
        frame_path = pathlib.Path(__file__).parent / "memory" / "kinect_latest.jpg"
        while True:
            time.sleep(0.5)
            with latest_frame_lock:
                f = latest_frame_jpeg[0]
            if f is not None:
                try:
                    frame_path.write_bytes(f)
                except: pass
    
    threading.Thread(target=frame_save_worker, daemon=True).start()

    
    def recvall(sock, count):
        buf = b''
        while count:
            newbuf = sock.recv(count)
            if not newbuf: return None
            buf += newbuf
            count -= len(newbuf)
        return buf

    print("Starting vision loop...")
    last_frame_time = 0

    while True:
        try:
            length_buf = recvall(frame_socket, 4)
            if not length_buf: break
            length = struct.unpack('i', length_buf)[0]
            
            frame_data = recvall(frame_socket, length)
            if not frame_data: break

            now = time.time()
            if now - last_frame_time < 0.1:
                continue  # Drop frame to cap YOLO at 10 FPS (saves GPU compute)
            last_frame_time = now

            # Raw Kinect ColorImageFormat.RgbResolution640x480Fps30 is BGRA32 (4 bytes per pixel)
            frame_np = np.frombuffer(frame_data, dtype=np.uint8).reshape((480, 640, 4))
            frame_bgr = frame_np[:, :, :3].copy() # Drop Alpha and copy to make writable for cv2
            clean_frame = frame_bgr.copy() # Clean frame for the LLM

            # 1. Object Detection
            results_obj = model_obj(frame_bgr, device="cpu", verbose=False)[0]
            boxes = results_obj.boxes
            objects = []
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                cls = int(box.cls[0].cpu().numpy())
                name = model_obj.names[cls]
                if name != "person":
                    objects.append({"name": name, "rect": (x1, y1, x2, y2)})
                    cv2.rectangle(frame_bgr, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                    cv2.putText(frame_bgr, name, (int(x1), int(y1)-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # 2. Pose Detection
            results_pose = model_pose(frame_bgr, device="cpu", verbose=False, conf=0.5)[0]
            
            user_cy = None
            pointing_at = None

            if len(results_pose.keypoints) > 0:
                kpts = results_pose.keypoints.xy[0].cpu().numpy()
                
                # Check nose keypoint (index 0)
                if len(kpts) > 0 and kpts[0][0] > 0 and kpts[0][1] > 0:
                    user_cy = kpts[0][1] # y-coordinate of nose
                    cv2.circle(frame_bgr, (int(kpts[0][0]), int(kpts[0][1])), 6, (0, 0, 255), -1) # Draw nose in red

                # Bounding box of person for tracking
                user_box = results_pose.boxes.xyxy[0].cpu().numpy() if len(results_pose.boxes) > 0 else None
                if user_box is not None:
                    if user_cy is None: user_cy = (user_box[1] + user_box[3]) / 2.0 # fallback
                    cv2.rectangle(frame_bgr, (int(user_box[0]), int(user_box[1])), (int(user_box[2]), int(user_box[3])), (255, 0, 0), 2)
                    cv2.putText(frame_bgr, "Pranav", (int(user_box[0]), int(user_box[1])-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
                    
                    # Draw skeleton
                    for k in kpts:
                        if k[0] > 0 and k[1] > 0:
                            cv2.circle(frame_bgr, (int(k[0]), int(k[1])), 4, (0, 255, 255), -1)
                
                # Check right arm (indices: 6=R_Shoulder, 8=R_Elbow, 10=R_Wrist)
                # Check left arm (indices: 5=L_Shoulder, 7=L_Elbow, 9=L_Wrist)
                
                def is_pointing(elbow, wrist):
                    if elbow[0] == 0 or wrist[0] == 0: return False, (0,0) # Not detected
                    # Vector from elbow to wrist
                    vx = wrist[0] - elbow[0]
                    vy = wrist[1] - elbow[1]
                    dist = np.sqrt(vx**2 + vy**2)
                    if dist < 20: return False, (0,0)
                    return True, (vx/dist, vy/dist)

                r_elbow, r_wrist = (0,0), (0,0)
                if len(kpts) > 10:
                    r_elbow = kpts[8]
                    r_wrist = kpts[10]

                pointing, vec = is_pointing(r_elbow, r_wrist)
                if pointing:
                    # Raycast to find intersection
                    best_obj = None
                    min_dist = float('inf')
                    
                    for obj in objects:
                        ox = (obj["rect"][0] + obj["rect"][2]) / 2.0
                        oy = (obj["rect"][1] + obj["rect"][3]) / 2.0
                        
                        # Vector from wrist to object center
                        wx = ox - r_wrist[0]
                        wy = oy - r_wrist[1]
                        
                        # Dot product to check alignment
                        dot = (wx * vec[0] + wy * vec[1])
                        if dot > 0: # Object is in front of the arm
                            # Perpendicular distance to the ray
                            proj_x = vec[0] * dot
                            proj_y = vec[1] * dot
                            perp_dist = np.sqrt((wx - proj_x)**2 + (wy - proj_y)**2)
                            
                            if perp_dist < 100 and perp_dist < min_dist:
                                min_dist = perp_dist
                                best_obj = obj["name"]
                    
                    if best_obj:
                        pointing_at = best_obj

            # Formulate state
            state_obj = {
                "user_visible": user_cy is not None,
                "objects_in_view": [o["name"] for o in objects],
                "pointing_at": pointing_at
            }
            
            import json
            state_json = json.dumps(state_obj)
            
            if state_json != last_state_json:
                threading.Thread(target=update_llm_state, args=(state_json,)).start()
                last_state_json = state_json

            # Draw ray
            if pointing_at and 'r_wrist' in locals() and 'vec' in locals():
                end_pt = (int(r_wrist[0] + vec[0]*500), int(r_wrist[1] + vec[1]*500))
                cv2.line(frame_bgr, (int(r_wrist[0]), int(r_wrist[1])), end_pt, (0, 0, 255), 3)

            # Motor Tracking logic
            if user_cy is not None and time.time() - last_motor_update > 1.5:
                target_y = 240 # Center of 480
                error = target_y - user_cy
                
                # Only move if head is significantly off center
                if error > 40 and current_angle < 27:
                    current_angle += 2
                    send_tilt(current_angle)
                    last_motor_update = time.time()
                elif error < -40 and current_angle > -27:
                    current_angle -= 2
                    send_tilt(current_angle)
                    last_motor_update = time.time()

            # Display UI
            status_text = "User Visible" if user_cy is not None else "No User"
            cv2.putText(frame_bgr, f"State: {status_text}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            cv2.putText(frame_bgr, f"Motor Angle: {current_angle}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            cv2.imshow("Buddy Vision UI", frame_bgr)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            # Encode latest clean frame as JPEG for LLM
            _, jpeg = cv2.imencode('.jpg', clean_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            with latest_frame_lock:
                latest_frame_jpeg[0] = jpeg.tobytes()

        except Exception as e:
            print("Vision loop error:", e)
            time.sleep(1)
            # Try to reconnect
            try:
                frame_socket.close()
                command_socket.close()
            except: pass
            break

if __name__ == "__main__":
    run_vision()
