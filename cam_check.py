import cv2

def list_cameras(max_index=10):
    print("Recherche des caméras disponibles...")
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            print(f"Caméra trouvée : index {i}")
            cap.release()
        else:
            print(f"Pas de caméra à l'index {i}")

list_cameras(10)