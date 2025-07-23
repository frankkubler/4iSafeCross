import os
import cv2
import logging

logger = logging.getLogger(__name__).getChild('utils')


def clean_files(dir, max_files=5, ext='.log'):
    files_2_clean = [f for f in os.listdir(dir) if f.endswith(ext)]

    # Sort the log files by creation time
    files_2_clean.sort(key=lambda f: os.path.getctime(os.path.join(dir, f)))

    # Keep only the last 10 files
    if len(files_2_clean) > max_files:
        for log_file in files_2_clean[:-max_files]:
            os.remove(os.path.join(dir, log_file))


def save_frame_to_file(frame, cid, timestamp):
    """Enregistre une frame dans un fichier en tant que tâche séparée"""
    try:
        output_dir = 'detections'
        os.makedirs(output_dir, exist_ok=True)
        clean_files(output_dir, max_files=220, ext='.jpg')  # Nettoyer les fichiers précédents
        filename = os.path.join(output_dir, f"cam_{cid}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg")
        cv2.imwrite(filename, frame)
        logger.info(f"Frame enregistrée: {filename}")
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement de la frame: {str(e)}")


def get_non_local_ips():
    import socket
    ip_list = set()
    try:
        for iface in socket.getaddrinfo(socket.gethostname(), None):
            ip = iface[4][0]
            if not ip.startswith("127.") and "." in ip:
                ip_list.add(ip)
    except Exception:
        pass
    if not ip_list:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if not ip.startswith("127."):
                    ip_list.add(ip)
        except Exception:
            pass
    return sorted(ip_list)


def get_docker_info():
    try:
        import subprocess
        result_ps = subprocess.run([
            "docker", "ps", "--format", "{{.Names}} ({{.Status}})"
        ], capture_output=True, text=True, timeout=5)
        if result_ps.returncode == 0 and result_ps.stdout.strip():
            info = "\n*Docker en cours :*\n" + '\n'.join(f"- {line}" for line in result_ps.stdout.strip().split('\n'))
            result_stats = subprocess.run([
                "docker", "stats", "--no-stream", "--format",
                "{{.Name}}: CPU={{.CPUPerc}}, MEM={{.MemUsage}}"
            ], capture_output=True, text=True, timeout=5)
            if result_stats.returncode == 0 and result_stats.stdout.strip():
                info += "\n*Stats Docker :*\n" + '\n'.join(f"- {line}" for line in result_stats.stdout.strip().split('\n'))
            return info
        return "\nAucun conteneur Docker en cours."
    except Exception as e:
        return f"\nErreur Docker : {e}"


def get_service_status(service_name):
    try:
        import subprocess
        result_status = subprocess.run(
            ["systemctl", "status", service_name, "--no-pager", "--full"],
            capture_output=True, text=True, timeout=5
        )
        status_lines = result_status.stdout.splitlines()
        info = {}
        for line in status_lines:
            if line.strip().startswith("Loaded:"):
                info['Loaded'] = line.strip().split('Loaded:', 1)[-1].strip()
            elif line.strip().startswith("Active:"):
                info['Active'] = line.strip().split('Active:', 1)[-1].strip()
            elif line.strip().startswith("Main PID:"):
                info['Main PID'] = line.strip().split('Main PID:', 1)[-1].strip()
            elif line.strip().startswith("Tasks:"):
                info['Tasks'] = line.strip().split('Tasks:', 1)[-1].strip()
            elif line.strip().startswith("Memory:"):
                info['Memory'] = line.strip().split('Memory:', 1)[-1].strip()
            elif line.strip().startswith("CPU:"):
                info['CPU'] = line.strip().split('CPU:', 1)[-1].strip()
        # Ajout température CPU (Jetson)
        try:
            import glob
            cpu_temps = []
            for path in glob.glob('/sys/class/thermal/thermal_zone*/temp'):
                with open(path) as f:
                    val = int(f.read().strip())
                    # Conversion en °C si nécessaire
                    if val > 1000:
                        val = val / 1000.0
                    cpu_temps.append(val)
            if cpu_temps:
                info['CPU Temp'] = f"{max(cpu_temps):.1f}°C"
        except Exception:
            pass
        # Ajout température GPU (Jetson)
        try:
            import subprocess
            import re
            proc = subprocess.Popen(["tegrastats"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            first_line = proc.stdout.readline()
            proc.terminate()
            # print("Sortie tegrastats :", first_line)
            match = re.search(r'gpu@([0-9]+[.,]?[0-9]*)C', first_line, re.IGNORECASE)
            if match:
                info['GPU Temp'] = f"{match.group(1)}°C"
            match = re.search(r'GR3D_FREQ\s+([0-9]+)%', first_line, re.IGNORECASE)
            if match:
                info['GPU Freq'] = f"{match.group(1)}%"    
        except Exception:
            pass
        msg = []
        if 'Loaded' in info:
            msg.append(f"Loaded: {info['Loaded']}")
        if 'Active' in info:
            msg.append(f"Active: {info['Active']}")
        if 'Main PID' in info:
            msg.append(f"Main PID: {info['Main PID']}")
        if 'Tasks' in info:
            msg.append(f"Tasks: {info['Tasks']}")
        if 'Memory' in info:
            msg.append(f"Memory: {info['Memory']}")
        if 'CPU' in info:
            msg.append(f"CPU: {info['CPU']}")
        if 'CPU Temp' in info:
            msg.append(f"Température CPU: {info['CPU Temp']}")
        if 'GPU Temp' in info:
            msg.append(f"Température GPU: {info['GPU Temp']}")
        return '\n'.join(msg) if msg else 'inconnu'
    except Exception as e:
        return f"Erreur : {e}"
