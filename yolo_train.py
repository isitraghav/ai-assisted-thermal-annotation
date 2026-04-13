# /// script
# dependencies = ["ultralytics", "torch", "torchvision"]
# ///
import os
from ultralytics import YOLO

def main():
    model = YOLO("runs/classify/thermal_anomaly_clf3/weights/best.pt") # Start from our balanced checkpoint instead of scratch
    
    print("Training YOLO Model with Context Dimming...")
    results = model.train(
        data=os.path.abspath("yolo_dataset"), 
        epochs=10,     
        imgsz=64,
        batch=32,
        augment=True,
        name="thermal_anomaly_clf_context"
    )
    print("Optimization Complete! Evaluation stored logically in:", results.dir if hasattr(results, "dir") else results)

if __name__ == "__main__":
    main()
