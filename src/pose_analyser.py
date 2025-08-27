

class PoseAnalyzer:
    """
    Classe pour analyser les keypoints de pose et déterminer la stature de la personne.
    Utilise les indices COCO pour les keypoints.
    Supporte keypoints avec ou sans confiance.
    """
    # Indices COCO pour les keypoints pertinents
    NOSE = 0
    LEFT_HIP = 11
    RIGHT_HIP = 12
    LEFT_KNEE = 13
    RIGHT_KNEE = 14
    LEFT_ANKLE = 15
    RIGHT_ANKLE = 16

    def __init__(self, confidence_threshold=0.5, knee_hip_threshold=35, ankle_spread_threshold=25, sitting_ratio_threshold=0.9):
        """
        - confidence_threshold : Seuil pour filtrer les keypoints (ignoré si pas de confiance).
        - knee_hip_threshold : Distance min entre genou et hanche pour 'debout'.
        - ankle_spread_threshold : Écart max entre chevilles pour 'assis' (chevilles proches = assis).
        - sitting_ratio_threshold : Seuil pour le ratio H2H/H2F pour confirmer 'assis' (ratio élevé = tête proche hanche).
        """
        self.confidence_threshold = confidence_threshold
        self.knee_hip_threshold = knee_hip_threshold
        self.ankle_spread_threshold = ankle_spread_threshold
        self.sitting_ratio_threshold = sitting_ratio_threshold

    def filter_keypoints_by_confidence(self, pose_keypoints):
        """
        Filtre les keypoints. Supporte deux formats :
        - Liste de dicts : [{"x": float, "y": float, "confidence": float}, ...]
        - Liste de listes : [[x, y], [x, y], ...] (sans confiance, utilise tous).
        Retourne : [(index, x, y, conf), ...]
        """
        filtered = []
        if not pose_keypoints:
            return filtered

        # Détecter le format
        if isinstance(pose_keypoints[0], dict):
            # Format dict avec confiance
            for i, kp in enumerate(pose_keypoints):
                conf = kp.get("confidence", 1.0)  # Défaut à 1.0 si absent
                if conf > self.confidence_threshold:
                    x = kp.get("x", 0)
                    y = kp.get("y", 0)
                    filtered.append((i, x, y, conf))
        elif isinstance(pose_keypoints[0], (list, tuple)) and len(pose_keypoints[0]) >= 2:
            # Format liste [x, y] sans confiance
            for i, kp in enumerate(pose_keypoints):
                x, y = kp[0], kp[1]
                filtered.append((i, x, y, 1.0))  # Confiance par défaut
        return filtered

    def _safe_average(self, values):
        """Calcule la moyenne en évitant division par zéro."""
        return sum(values) / len(values) if values else 0

    def _calculate_spread(self, points):
        """Calcule l'écart max entre points (ex: chevilles)."""
        if len(points) < 2:
            return 0
        x_coords = [p[0] for p in points]
        return max(x_coords) - min(x_coords)

    def calculate_ratios(self, pose_keypoints):
        """
        Calcule les distances head2hip, hip2feet et leur ratio.
        Utilise le nez si disponible, sinon le point le plus haut comme tête.
        Retourne un dict avec les valeurs, ou None si keypoints manquants.
        """
        filtered_kps = self.filter_keypoints_by_confidence(pose_keypoints)
        if not filtered_kps:
            return None

        kp_dict = {idx: (x, y) for idx, x, y, conf in filtered_kps}

        # Utiliser le nez si disponible, sinon le point le plus haut
        if self.NOSE in kp_dict:
            head_x, head_y = kp_dict[self.NOSE]
        else:
            # Trouver le point avec le y le plus petit (plus haut)
            if not kp_dict:
                return None
            head_idx = min(kp_dict, key=lambda idx: kp_dict[idx][1])
            head_x, head_y = kp_dict[head_idx]

        # Moyenne hanches
        hip_positions = [kp_dict[idx] for idx in [self.LEFT_HIP, self.RIGHT_HIP] if idx in kp_dict]
        if not hip_positions:
            return None
        avg_hip_x = self._safe_average([x for x, y in hip_positions])
        avg_hip_y = self._safe_average([y for x, y in hip_positions])

        # Moyenne chevilles
        ankle_positions = [kp_dict[idx] for idx in [self.LEFT_ANKLE, self.RIGHT_ANKLE] if idx in kp_dict]
        if not ankle_positions:
            return None
        avg_ankle_x = self._safe_average([x for x, y in ankle_positions])
        avg_ankle_y = self._safe_average([y for x, y in ankle_positions])

        # Distances euclidiennes
        head_to_hip = ((head_x - avg_hip_x)**2 + (head_y - avg_hip_y)**2)**0.5
        hip_to_feet = ((avg_hip_x - avg_ankle_x)**2 + (avg_hip_y - avg_ankle_y)**2)**0.5

        ratio = head_to_hip / hip_to_feet if hip_to_feet > 0 else 0

        return {
            'head_to_hip_distance': head_to_hip,
            'hip_to_foot_distance': hip_to_feet,
            'h2h_h2f_ratio': ratio
        }

    def analyze_stature(self, pose_keypoints, debug=False):
        """
        Analyse la stature basée sur les keypoints filtrés.
        Retourne : 'debout', 'assis', 'jambes_masquees', 'marchant', ou 'inconnu'
        - debug : Si True, retourne aussi les valeurs calculées pour inspection.
        """
        filtered_kps = self.filter_keypoints_by_confidence(pose_keypoints)
        if not filtered_kps:
            return ('inconnu', {}) if debug else 'inconnu'

        kp_dict = {idx: (x, y) for idx, x, y, conf in filtered_kps}

        # Vérifier présence
        hips_present = self.LEFT_HIP in kp_dict or self.RIGHT_HIP in kp_dict
        knees_present = self.LEFT_KNEE in kp_dict or self.RIGHT_KNEE in kp_dict
        ankles_present = self.LEFT_ANKLE in kp_dict or self.RIGHT_ANKLE in kp_dict

        if not hips_present:
            return ('jambes_masquees', {}) if debug else 'jambes_masquees'

        # Collecter positions
        hip_positions = [kp_dict[idx] for idx in [self.LEFT_HIP, self.RIGHT_HIP] if idx in kp_dict]
        knee_positions = [kp_dict[idx] for idx in [self.LEFT_KNEE, self.RIGHT_KNEE] if idx in kp_dict]
        ankle_positions = [kp_dict[idx] for idx in [self.LEFT_ANKLE, self.RIGHT_ANKLE] if idx in kp_dict]

        if not knee_positions:
            return ('jambes_masquees', {}) if debug else 'jambes_masquees'

        # Moyennes y (rappel : y=0 haut, y croissant vers bas)
        avg_hip_y = self._safe_average([y for x, y in hip_positions])
        avg_knee_y = self._safe_average([y for x, y in knee_positions])
        avg_ankle_y = self._safe_average([y for x, y in ankle_positions])

        # Écart chevilles (pour détecter marche : écart > seuil = jambes écartées)
        ankle_spread = self._calculate_spread(ankle_positions)

        # Calculer les ratios si possible
        ratios = self.calculate_ratios(pose_keypoints)
        ratio_value = ratios['h2h_h2f_ratio'] if ratios else 0

        # Logique corrigée
        knee_hip_diff = avg_knee_y - avg_hip_y  # Positif si genou plus bas que hanche (debout)
        
        if ankles_present and avg_hip_y < avg_knee_y < avg_ankle_y and knee_hip_diff > self.knee_hip_threshold:
            # Debout : hanche < genou < cheville (hanche haute, cheville basse)
            if ankle_spread > self.ankle_spread_threshold:
                stature = 'marchant'  # Jambes écartées = mouvement
            else:
                stature = 'debout'
        elif knees_present and abs(knee_hip_diff) < 30 and avg_ankle_y > avg_knee_y and (not ratios or ratio_value > self.sitting_ratio_threshold):
            # Assis : genou proche hanche, cheville plus basse, et ratio élevé (tête proche hanche)
            stature = 'assis'
        elif not ankles_present:
            stature = 'jambes_masquees'
        else:
            stature = 'inconnu'

        if debug:
            debug_info = {
                'avg_hip_y': avg_hip_y,
                'avg_knee_y': avg_knee_y,
                'avg_ankle_y': avg_ankle_y,
                'knee_hip_diff': knee_hip_diff,
                'ankle_spread': ankle_spread,
                'hips_present': hips_present,
                'knees_present': knees_present,
                'ankles_present': ankles_present,
                'ratios': ratios
            }
            return stature, debug_info
        return stature
