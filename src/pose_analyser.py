

class PoseAnalyzer:
    """
    Classe pour analyser les keypoints de pose et déterminer la stature de la personne.
    Utilise les indices COCO pour les keypoints.
    Supporte keypoints avec ou sans confiance.
    Version améliorée avec adaptation selon la position dans l'image.
    """
    # Indices COCO pour les keypoints pertinents
    NOSE = 0
    LEFT_HIP = 11
    RIGHT_HIP = 12
    LEFT_KNEE = 13
    RIGHT_KNEE = 14
    LEFT_ANKLE = 15
    RIGHT_ANKLE = 16

    # ═══════════════════════════════════════════════════════════════════════════════
    # 🎯 CONFIGURATION DES ZONES D'ADAPTATION
    # ═══════════════════════════════════════════════════════════════════════════════
    
    # Délimitation des zones (en pourcentage de la hauteur d'image)
    ZONE_HIGH_LIMIT = 0.28      # 28% supérieur = fond de l'image (personnes éloignées)
    ZONE_MIDDLE_LIMIT = 0.6     # 60% = zone médiane (distance normale)
    # Zone LOW = reste (60-100%) = premier plan (personnes proches)
    
    # ───────────────────────────────────────────────────────────────────────────────
    # 🔵 ZONE HIGH (Fond 0-28%) - Petites silhouettes éloignées
    # ───────────────────────────────────────────────────────────────────────────────
    ZONE_HIGH_CONFIG = {
        # Seuils de proximité pour détection "assis"
        'knee_hip_proximity_threshold': 25,    # Distance max genoux-hanches pour "assis"
        'ankle_knee_threshold': 12,            # Distance max chevilles-genoux pour "assis"
        
        # Facteurs d'adaptation des seuils principaux
        'knee_hip_factor': 0.8,                # Réduction 20% du seuil debout
        'ankle_spread_factor': 0.85,           # Réduction 15% du seuil marche
        'sitting_ratio_factor': 0.9,           # Réduction 10% du ratio assis
        
        # Multiplicateurs pour logique de détection
        'sitting_ratio_multiplier': 1.4,       # Ratio très élevé requis pour "assis"
        'knee_hip_strict_factor': 0.7,         # Genoux très proches hanches
        'ankle_knee_strict_factor': 0.8,       # Chevilles cachées modérées
        'ankle_knee_very_strict_factor': 0.6,  # Chevilles très cachées
        'standing_knee_hip_factor': 0.6,       # Seuil debout réduit
        'standing_ankle_knee_factor': 0.7,     # Seuil cheville-genou réduit
        'standing_ratio_factor': 1.1,          # Ratio debout plus strict
    }
    
    # ───────────────────────────────────────────────────────────────────────────────
    # 🟡 ZONE MIDDLE (Médiane 28-60%) - Proportions équilibrées
    # ───────────────────────────────────────────────────────────────────────────────
    ZONE_MIDDLE_CONFIG = {
        # Seuils de proximité pour détection "assis" - OPTIMISÉS POUR CONDUCTEURS
        'knee_hip_proximity_threshold': 50,    # Augmenté de 45 à 50 (plus tolérant)
        'ankle_knee_threshold': 25,            # Augmenté de 20 à 25 (chevilles cachées)
        
        # Facteurs d'adaptation des seuils principaux
        'knee_hip_factor': 0.85,               # Réduit de 0.9 à 0.85 (plus strict debout)
        'ankle_spread_factor': 0.9,            # Réduit de 0.95 à 0.9 (moins de marche)
        'sitting_ratio_factor': 1.0,           # Aucune modification du ratio
        
        # Multiplicateurs pour logique de détection - OPTIMISÉS CONDUCTEURS
        'sitting_ratio_multiplier': 1.1,       # Réduit de 1.2 à 1.1 (plus facile "assis")
        'exclusion_ankle_knee_factor': 40,     # Réduit de 50 à 40 (moins d'exclusion)
        'exclusion_knee_hip_factor': 0.7,      # Réduit de 0.8 à 0.7 (moins strict)
        'standing_ratio_factor': 0.95,         # Réduit de 1.0 à 0.95 (plus strict debout)
        
        # NOUVEAUX PARAMÈTRES pour améliorer détection conducteurs
        'sitting_ankle_knee_factor': 1.3,      # Chevilles cachées plus tolérantes
        'sitting_knee_hip_strict_factor': 0.8, # Genoux proches hanches
        'standing_knee_hip_min_factor': 0.9,   # Seuil minimum debout plus strict
    }
    
    # ───────────────────────────────────────────────────────────────────────────────
    # 🔴 ZONE LOW (Premier plan 60-100%) - Grandes silhouettes proches
    # ───────────────────────────────────────────────────────────────────────────────
    ZONE_LOW_CONFIG = {
        # Seuils de proximité pour détection "assis"
        'knee_hip_proximity_threshold': 45,    # Distance max genoux-hanches
        'ankle_knee_threshold': 20,            # Distance max chevilles-genoux
        
        # Facteurs d'adaptation des seuils principaux
        'knee_hip_factor': 1.0,                # Aucune réduction
        'ankle_spread_factor': 1.0,            # Aucune réduction
        'sitting_ratio_factor': 1.1,           # Augmentation 10% tolérance
        
        # Multiplicateurs pour logique de détection renforcée
        'sitting_ankle_knee_factor': 1.2,      # Chevilles cachées plus strictes
        'sitting_ratio_multiplier': 1.3,       # Ratio très élevé pour assis
        'sitting_knee_hip_factor': 0.8,        # Genoux proches hanches strict
        'exclusion_ankle_knee_factor': 1.5,    # Exclusion chevilles visibles
        'exclusion_knee_hip_factor': 0.7,      # Exclusion debout évident
        'standing_knee_hip_factor': 0.9,       # Seuil debout légèrement réduit
        'standing_ankle_knee_factor': 0.9,     # Seuil cheville-genou réduit
        'standing_ratio_factor': 0.9,          # Ratio debout plus strict
    }
    
    # ═══════════════════════════════════════════════════════════════════════════════

    def __init__(self, confidence_threshold=0.5, knee_hip_threshold=35, ankle_spread_threshold=25,
                 sitting_ratio_threshold=0.9, enable_zone_adaptation=True, image_height=1080):
        """
        Initialisation du PoseAnalyzer avec adaptation zonale.
        
        Paramètres principaux:
        - confidence_threshold : Seuil pour filtrer les keypoints (ignoré si pas de confiance).
        - knee_hip_threshold : Distance min entre genou et hanche pour 'debout'.
        - ankle_spread_threshold : Écart max entre chevilles pour 'assis' (chevilles proches = assis).
        - sitting_ratio_threshold : Seuil pour le ratio H2H/H2F pour confirmer 'assis' (ratio élevé = tête proche hanche).
        - enable_zone_adaptation : Active l'adaptation des seuils selon la zone dans l'image.
        - image_height : Hauteur de l'image pour les calculs d'adaptation.
        
        Zones d'adaptation automatique:
        - HIGH (0-28%) : Fond, petites silhouettes, seuils réduits
        - MIDDLE (28-60%) : Médiane, seuils standards
        - LOW (60-100%) : Premier plan, grandes silhouettes, seuils adaptés
        """
        # Paramètres de base
        self.confidence_threshold = confidence_threshold
        self.knee_hip_threshold = knee_hip_threshold
        self.ankle_spread_threshold = ankle_spread_threshold
        self.sitting_ratio_threshold = sitting_ratio_threshold
        self.enable_zone_adaptation = enable_zone_adaptation
        self.image_height = image_height
        
        # Configuration des zones (utilise les constantes de classe)
        self.zone_high = self.ZONE_HIGH_LIMIT
        self.zone_middle = self.ZONE_MIDDLE_LIMIT
        
        # Stockage des configurations par zone pour accès rapide
        self.zone_configs = {
            'high': self.ZONE_HIGH_CONFIG,
            'middle': self.ZONE_MIDDLE_CONFIG,
            'low': self.ZONE_LOW_CONFIG
        }

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

    def _get_person_zone(self, pose_keypoints):
        """
        Détermine dans quelle zone verticale de l'image se trouve la personne.
        Retourne: 'high', 'middle', ou 'low'
        """
        if not pose_keypoints:
            return 'middle'
            
        filtered_kps = self.filter_keypoints_by_confidence(pose_keypoints)
        if not filtered_kps:
            return 'middle'
            
        # Utiliser le centre de masse vertical des keypoints visibles
        y_coords = [y for idx, x, y, conf in filtered_kps]
        avg_y = self._safe_average(y_coords)
        
        # Convertir en pourcentage de la hauteur d'image
        y_ratio = avg_y / self.image_height if self.image_height > 0 else 0.5
        
        if y_ratio <= self.zone_high:
            return 'high'
        elif y_ratio <= self.zone_middle:
            return 'middle'
        else:
            return 'low'

    def _get_adaptive_thresholds(self, zone, pose_keypoints):
        """
        Calcule des seuils adaptatifs selon la zone et la taille apparente de la personne.
        Utilise les configurations centralisées définies au début de la classe.
        """
        base_knee_hip = self.knee_hip_threshold
        base_ankle_spread = self.ankle_spread_threshold
        base_sitting_ratio = self.sitting_ratio_threshold
        
        if not self.enable_zone_adaptation:
            return base_knee_hip, base_ankle_spread, base_sitting_ratio
            
        # Estimer la taille apparente de la personne (distance verticale max entre keypoints)
        filtered_kps = self.filter_keypoints_by_confidence(pose_keypoints)
        if len(filtered_kps) < 2:
            person_height = 100  # Valeur par défaut
        else:
            y_coords = [y for idx, x, y, conf in filtered_kps]
            person_height = max(y_coords) - min(y_coords)
        
        # Facteur d'échelle basé sur la taille apparente
        # Plus la personne semble petite (loin), plus on réduit les seuils
        scale_factor = max(0.3, min(2.0, person_height / 200))  # Normalisé autour de 200px de hauteur
        
        # Récupérer la configuration de la zone
        config = self.zone_configs[zone]
        
        # Application des facteurs d'adaptation selon la configuration de zone
        knee_hip_adapted = base_knee_hip * scale_factor * config['knee_hip_factor']
        ankle_spread_adapted = base_ankle_spread * scale_factor * config['ankle_spread_factor']
        sitting_ratio_adapted = base_sitting_ratio * config['sitting_ratio_factor']
            
        return knee_hip_adapted, ankle_spread_adapted, sitting_ratio_adapted

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
        Version améliorée avec adaptation selon la zone dans l'image.
        """
        filtered_kps = self.filter_keypoints_by_confidence(pose_keypoints)
        if not filtered_kps:
            return ('inconnu', {}) if debug else 'inconnu'

        # Déterminer la zone de l'image et adapter les seuils
        zone = self._get_person_zone(pose_keypoints)
        knee_hip_threshold, ankle_spread_threshold, sitting_ratio_threshold = self._get_adaptive_thresholds(zone, pose_keypoints)
        
        kp_dict = {idx: (x, y) for idx, x, y, conf in filtered_kps}

        # Vérifier présence
        hips_present = self.LEFT_HIP in kp_dict or self.RIGHT_HIP in kp_dict
        knees_present = self.LEFT_KNEE in kp_dict or self.RIGHT_KNEE in kp_dict
        ankles_present = self.LEFT_ANKLE in kp_dict or self.RIGHT_ANKLE in kp_dict

        if not hips_present:
            debug_info = {'zone': zone, 'adapted_thresholds': (knee_hip_threshold, ankle_spread_threshold, sitting_ratio_threshold)} if debug else {}
            return ('jambes_masquees', debug_info) if debug else 'jambes_masquees'

        # Collecter positions
        hip_positions = [kp_dict[idx] for idx in [self.LEFT_HIP, self.RIGHT_HIP] if idx in kp_dict]
        knee_positions = [kp_dict[idx] for idx in [self.LEFT_KNEE, self.RIGHT_KNEE] if idx in kp_dict]
        ankle_positions = [kp_dict[idx] for idx in [self.LEFT_ANKLE, self.RIGHT_ANKLE] if idx in kp_dict]

        if not knee_positions:
            debug_info = {'zone': zone, 'adapted_thresholds': (knee_hip_threshold, ankle_spread_threshold, sitting_ratio_threshold)} if debug else {}
            return ('jambes_masquees', debug_info) if debug else 'jambes_masquees'

        # Moyennes y (rappel : y=0 haut, y croissant vers bas)
        avg_hip_y = self._safe_average([y for x, y in hip_positions])
        avg_knee_y = self._safe_average([y for x, y in knee_positions])
        avg_ankle_y = self._safe_average([y for x, y in ankle_positions])

        # Écart chevilles (pour détecter marche : écart > seuil = jambes écartées)
        ankle_spread = self._calculate_spread(ankle_positions)

        # Calculer les ratios si possible
        ratios = self.calculate_ratios(pose_keypoints)
        ratio_value = ratios['h2h_h2f_ratio'] if ratios else 0

        # Logique corrigée avec seuils adaptatifs
        knee_hip_diff = avg_knee_y - avg_hip_y  # Positif si genou plus bas que hanche (debout)
        
        # Récupération des seuils adaptatifs selon la zone (centralisés)
        config = self.zone_configs[zone]
        knee_hip_proximity_threshold = config['knee_hip_proximity_threshold']
        ankle_knee_threshold = config['ankle_knee_threshold']
        
        # Calculer la distance verticale cheville-genou pour détecter position assise
        ankle_knee_diff = avg_ankle_y - avg_knee_y if ankles_present else float('inf')
        
        # Logique adaptée pour la zone haute (fond de l'image)
        if zone == 'high':
            # Dans le fond, être plus strict sur les critères "assis" pour éviter faux positifs
            is_sitting_posture = (
                knees_present and
                (
                    # Ratio très élevé (plus strict pour éviter confusion)
                    (ratios and ratio_value > sitting_ratio_threshold * 1.4) or
                    # Genoux très proches des hanches ET chevilles cachées
                    (abs(knee_hip_diff) < knee_hip_proximity_threshold * 0.7 and
                     (not ankles_present or ankle_knee_diff < ankle_knee_threshold * 0.8)) or
                    # Chevilles vraiment très cachées (cas évident d'assis)
                    (ankles_present and ankle_knee_diff < ankle_knee_threshold * 0.6)
                ) and
                # Exclusion: si ordre vertical respecté avec distances suffisantes → pas assis
                not (ankles_present and avg_hip_y < avg_knee_y < avg_ankle_y and
                     knee_hip_diff > knee_hip_threshold * 0.5 and
                     ankle_knee_diff > ankle_knee_threshold * 0.7)
            )
            
            # Position debout dans le fond: critères moins restrictifs mais plus discriminants
            is_standing_posture = (
                ankles_present and
                avg_hip_y < avg_knee_y < avg_ankle_y and  # Ordre vertical respecté
                knee_hip_diff > knee_hip_threshold * 0.6 and  # Moins restrictif
                ankle_knee_diff > ankle_knee_threshold * 0.7 and  # Moins restrictif
                not is_sitting_posture and
                # Ratio cohérent avec position debout (plus strict)
                (not ratios or ratio_value < sitting_ratio_threshold * 1.1)
            )
        else:
            # Logique standard pour zones middle et low
            # Zone low: critères adaptés aux grandes silhouettes du premier plan
            if zone == 'low':
                # Au premier plan, les distances sont plus importantes, critères renforcés
                is_sitting_posture = (
                    knees_present and
                    (
                        # Critère 1: Genoux vraiment proches des hanches ET pas debout évident
                        (abs(knee_hip_diff) < knee_hip_proximity_threshold and
                         (not ankles_present or ankle_knee_diff < ankle_knee_threshold * 1.2)) or
                        # Critère 2: Chevilles clairement cachées (très caractéristique d'assis)
                        (ankles_present and ankle_knee_diff < ankle_knee_threshold * 0.8) or
                        # Critère 3: Ratio très élevé + genoux pas trop bas
                        (ratios and ratio_value > sitting_ratio_threshold * 1.3 and
                         knee_hip_diff < knee_hip_proximity_threshold * 0.8)
                    ) and
                    # Exclusion forte: si chevilles sont bien visibles ET bien en dessous des genoux
                    not (ankles_present and ankle_knee_diff > ankle_knee_threshold * 1.5 and
                         knee_hip_diff > knee_hip_proximity_threshold * 0.7)
                )
                
                # Position debout au premier plan: critères plus stricts pour éviter confusion
                is_standing_posture = (
                    ankles_present and
                    avg_hip_y < avg_knee_y < avg_ankle_y and  # Ordre vertical strict
                    knee_hip_diff > knee_hip_threshold * 0.9 and  # Seuil moins réduit
                    ankle_knee_diff > ankle_knee_threshold * 0.9 and  # Seuil moins réduit
                    not is_sitting_posture and
                    # Ratio cohérent avec position debout (plus strict)
                    (not ratios or ratio_value < sitting_ratio_threshold * 0.9)
                )
            else:
                # Zone middle: logique optimisée pour les conducteurs
                config = self.zone_configs['middle']
                is_sitting_posture = (
                    knees_present and
                    (
                        # Critère 1: Genoux proches des hanches (plus tolérant avec nouveau seuil)
                        abs(knee_hip_diff) < knee_hip_proximity_threshold or
                        # Critère 2: Chevilles cachées ou très proches des genoux (tolérance accrue)
                        (ankles_present and ankle_knee_diff < ankle_knee_threshold * config.get('sitting_ankle_knee_factor', 1.3)) or
                        # Critère 3: Ratio élevé (seuil réduit pour faciliter détection "assis")
                        (ratios and ratio_value > sitting_ratio_threshold * config.get('sitting_ratio_multiplier', 1.1)) or
                        # Critère 4: Genoux vraiment très proches hanches (conducteur typique)
                        abs(knee_hip_diff) < knee_hip_proximity_threshold * config.get('sitting_knee_hip_strict_factor', 0.8)
                    ) and
                    # Exclusion moins stricte pour zone middle (conducteurs)
                    not (ankles_present and 
                         ankle_knee_diff > config.get('exclusion_ankle_knee_factor', 40) and
                         knee_hip_diff > knee_hip_threshold * config.get('exclusion_knee_hip_factor', 0.7))
                )
                
                # Position debout zone middle: critères plus stricts pour éviter faux positifs
                config = self.zone_configs['middle']
                is_standing_posture = (
                    ankles_present and
                    avg_hip_y < avg_knee_y < avg_ankle_y and  # Ordre strict: hanche < genou < cheville
                    knee_hip_diff > knee_hip_threshold * config.get('standing_knee_hip_min_factor', 0.9) and  # Plus strict
                    ankle_knee_diff > ankle_knee_threshold and  # Distance suffisante cheville-genou
                    not is_sitting_posture and  # Pas déjà identifié comme assis
                    # Ratio plus strict pour position debout en zone middle
                    (not ratios or ratio_value < sitting_ratio_threshold * config.get('standing_ratio_factor', 0.95))
                )
        
        if is_sitting_posture:
            stature = 'assis'
        elif is_standing_posture:
            # Debout : vérifier si c'est en mouvement (jambes écartées)
            if ankle_spread > ankle_spread_threshold:
                stature = 'marchant'  # Jambes écartées = mouvement
            else:
                stature = 'debout'
        elif not ankles_present:
            stature = 'jambes_masquees'
        else:
            # Logique de fallback pour éviter les "inconnu" quand on a des keypoints valides
            # Si on a des hanches et genoux mais pas de classification claire
            if hips_present and knees_present:
                # Heuristique basée sur l'ordre vertical des points
                if ankles_present and avg_hip_y < avg_knee_y < avg_ankle_y:
                    # Ordre vertical respecté = probablement debout
                    if ankle_spread > ankle_spread_threshold * 0.7:  # Seuil réduit
                        stature = 'marchant'
                    else:
                        stature = 'debout'
                elif ankles_present and ankle_knee_diff < ankle_knee_threshold * 1.5:
                    # Chevilles proches des genoux = probablement assis
                    stature = 'assis'
                else:
                    # Cas par défaut: utiliser le ratio si disponible
                    if ratios and ratio_value > sitting_ratio_threshold:
                        stature = 'assis'
                    else:
                        stature = 'debout'  # Choix par défaut plutôt qu'inconnu
            else:
                stature = 'inconnu'

        if debug:
            debug_info = {
                'zone': zone,
                'adapted_thresholds': {
                    'knee_hip_threshold': knee_hip_threshold,
                    'ankle_spread_threshold': ankle_spread_threshold,
                    'sitting_ratio_threshold': sitting_ratio_threshold,
                    'knee_hip_proximity_threshold': knee_hip_proximity_threshold,
                    'ankle_knee_threshold': ankle_knee_threshold
                },
                'original_thresholds': {
                    'knee_hip_threshold': self.knee_hip_threshold,
                    'ankle_spread_threshold': self.ankle_spread_threshold,
                    'sitting_ratio_threshold': self.sitting_ratio_threshold
                },
                'avg_hip_y': avg_hip_y,
                'avg_knee_y': avg_knee_y,
                'avg_ankle_y': avg_ankle_y,
                'knee_hip_diff': knee_hip_diff,
                'ankle_knee_diff': ankle_knee_diff,
                'ankle_spread': ankle_spread,
                'hips_present': hips_present,
                'knees_present': knees_present,
                'ankles_present': ankles_present,
                'ratios': ratios,
                'is_sitting_posture': is_sitting_posture,
                'is_standing_posture': is_standing_posture
            }
            return stature, debug_info
        return stature
