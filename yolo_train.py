# /// script
# dependencies = ["ultralytics", "torch", "torchvision"]
# ///
import os
from ultralytics import YOLO

def main():
    model = YOLO("yolov8n-cls.pt")
    
    print("Training YOLO Model...")
    results = model.train(
        data=os.path.abspath("yolo_dataset"), 
        epochs=10,     
        imgsz=64,
        batch=32,
        augment=True, # Allow random flips for minorities
        name="thermal_anomaly_clf"
    )
    print("Optimization Complete! Evaluation stored logically in:", results.dir if hasattr(results, "dir") else results)

if __name__ == "__main__":
    main()
