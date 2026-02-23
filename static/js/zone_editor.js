/**
 * Zone Editor pour 4iSafeCross
 *
 * Éditeur visuel de polygones de zones de détection.
 * Basé sur Fabric.js, inspiré de PolygonZones.
 *
 * Fonctionnalités :
 * - Chargement du snapshot caméra comme fond
 * - Affichage des zones existantes depuis zones.ini
 * - Dessin de nouveaux polygones (clic gauche = point, clic droit = fermer)
 * - Sélection et suppression de zones
 * - Sauvegarde vers le backend avec rechargement à chaud
 */

(function () {
    "use strict";

    // === Configuration ===
    const SNAP_DIST = 10; // Distance de snap aux bords (pixels)
    const POINT_RADIUS = 5;
    const LINE_WIDTH = 2;
    const FILL_OPACITY = 0.25;
    const MAX_CANVAS_WIDTH = 1400;

    // Palette de couleurs automatiques (RGB)
    const COLOR_PALETTE = [
        [128, 255, 0],   // Vert clair
        [255, 128, 0],   // Orange
        [255, 255, 0],   // Jaune
        [0, 255, 255],   // Cyan
        [255, 0, 255],   // Magenta
        [0, 128, 255],   // Bleu clair
        [255, 64, 64],   // Rouge clair
        [128, 0, 255],   // Violet
    ];

    // === État ===
    let fabricCanvas = null;
    let camId = null;
    let imageWidth = 0;   // Dimensions réelles de l'image
    let imageHeight = 0;
    let canvasWidth = 0;  // Dimensions du canvas (éventuellement réduit)
    let canvasHeight = 0;
    let scaleFactor = 1;  // imageWidth / canvasWidth

    // Polygones terminés : [{name, polygon (coords canvas), color, fabricObj}]
    let completedZones = [];
    let selectedZoneIndex = -1;

    // État du dessin en cours
    let isDrawing = false;
    let currentPoints = [];
    let tempLines = [];
    let tempCircles = [];
    let previewLine = null;

    // === Éléments DOM ===
    const $ = (id) => document.getElementById(id);

    // === Initialisation ===
    function init() {
        camId = parseInt($("editor-canvas").dataset.camId, 10);

        setupButtons();
        loadSnapshot();
    }

    /**
     * Charge le snapshot de la caméra et initialise le canvas.
     */
    function loadSnapshot() {
        showLoading(true);
        setStatus("Chargement du snapshot...");

        const img = new Image();
        img.crossOrigin = "anonymous";

        img.onload = function () {
            imageWidth = img.naturalWidth;
            imageHeight = img.naturalHeight;

            // Calculer le facteur d'échelle si l'image est trop grande
            if (imageWidth > MAX_CANVAS_WIDTH) {
                scaleFactor = imageWidth / MAX_CANVAS_WIDTH;
                canvasWidth = MAX_CANVAS_WIDTH;
                canvasHeight = Math.round(imageHeight / scaleFactor);
            } else {
                scaleFactor = 1;
                canvasWidth = imageWidth;
                canvasHeight = imageHeight;
            }

            initCanvas(img);
            loadExistingZones();
        };

        img.onerror = function () {
            showLoading(false);
            setStatus("Erreur : impossible de charger le snapshot caméra", "error");
            showToast("Caméra hors ligne ou flux indisponible", "error");
        };

        // Ajouter un timestamp pour éviter le cache navigateur
        img.src = `/snapshot/${camId}?t=${Date.now()}`;
    }

    /**
     * Initialise le canvas Fabric.js avec le snapshot comme fond.
     */
    function initCanvas(img) {
        // Détruire l'ancien canvas si existe
        if (fabricCanvas) {
            fabricCanvas.dispose();
        }

        // Recréer l'élément canvas
        const wrapper = $("canvas-wrapper");
        wrapper.innerHTML = "";
        const canvasEl = document.createElement("canvas");
        canvasEl.id = "editor-canvas";
        canvasEl.dataset.camId = camId;
        canvasEl.width = canvasWidth;
        canvasEl.height = canvasHeight;
        wrapper.appendChild(canvasEl);

        fabricCanvas = new fabric.Canvas("editor-canvas", {
            width: canvasWidth,
            height: canvasHeight,
            selection: false,
            hoverCursor: "crosshair",
            defaultCursor: "crosshair",
        });

        // Placer l'image en fond
        const fabricImg = new fabric.Image(img);
        fabricCanvas.setBackgroundImage(fabricImg, function () {
            const bgImage = fabricCanvas.backgroundImage;
            if (bgImage) {
                bgImage.scaleX = canvasWidth / bgImage.width;
                bgImage.scaleY = canvasHeight / bgImage.height;
            }
            fabricCanvas.renderAll();
        });

        setupCanvasEvents();
        updateImageInfo();
    }

    /**
     * Charge les zones existantes depuis l'API et les dessine sur le canvas.
     */
    function loadExistingZones() {
        fetch(`/api/zones/${camId}`)
            .then((res) => res.json())
            .then((zones) => {
                completedZones = [];
                zones.forEach((zone) => {
                    // Convertir les coordonnées réelles → canvas
                    const canvasPolygon = zone.polygon.map((pt) => [
                        pt[0] / scaleFactor,
                        pt[1] / scaleFactor,
                    ]);
                    const color = zone.color || getNextColor();
                    const fabricObj = drawCompletedPolygon(canvasPolygon, color);

                    completedZones.push({
                        name: zone.name,
                        polygon: canvasPolygon,
                        color: color,
                        fabricObj: fabricObj,
                    });
                });

                updateZoneList();
                showLoading(false);
                setStatus(
                    `${completedZones.length} zone(s) chargée(s) — Image ${imageWidth}×${imageHeight}px`
                );
            })
            .catch((err) => {
                console.error("Erreur chargement zones:", err);
                showLoading(false);
                setStatus("Zones chargées (aucune existante)");
            });
    }

    // === Événements canvas ===
    function setupCanvasEvents() {
        // Clic gauche : ajouter un point ou sélectionner une zone
        fabricCanvas.on("mouse:down", function (opt) {
            if (opt.e.button !== 0) return;
            const pointer = fabricCanvas.getPointer(opt.e);

            if (!isDrawing) {
                // Vérifier si on clique sur une zone existante
                const clickedZoneIdx = findZoneAtPoint(pointer.x, pointer.y);
                if (clickedZoneIdx >= 0) {
                    selectZone(clickedZoneIdx);
                    return;
                }
                // Sinon démarrer un nouveau polygone
                isDrawing = true;
                deselectZone();
            }

            // Snap aux bords
            const x = snapToBorder(pointer.x, canvasWidth);
            const y = snapToBorder(pointer.y, canvasHeight);
            addPoint(x, y);
        });

        // Clic droit : fermer le polygone
        fabricCanvas.upperCanvasEl.addEventListener("contextmenu", function (e) {
            e.preventDefault();
            if (isDrawing && currentPoints.length >= 3) {
                closePolygon();
            }
        });

        // Preview line en mouvement
        fabricCanvas.on("mouse:move", function (opt) {
            if (isDrawing && currentPoints.length > 0) {
                updatePreviewLine(opt);
            }
            // Mettre à jour les coordonnées dans la barre de statut
            const pointer = fabricCanvas.getPointer(opt.e);
            const realX = Math.round(pointer.x * scaleFactor);
            const realY = Math.round(pointer.y * scaleFactor);
            $("status-coords").textContent = `${realX}, ${realY}`;
        });

        // Touche Suppr : supprimer la zone sélectionnée
        document.addEventListener("keydown", function (e) {
            if (e.key === "Delete" && selectedZoneIndex >= 0) {
                deleteZone(selectedZoneIndex);
            }
            // Échap : annuler le dessin en cours
            if (e.key === "Escape" && isDrawing) {
                cancelDrawing();
            }
        });
    }

    /**
     * Snap une coordonnée au bord si elle est proche.
     */
    function snapToBorder(val, max) {
        if (val < SNAP_DIST) return 0;
        if (val > max - SNAP_DIST) return max;
        return val;
    }

    /**
     * Ajoute un point au polygone en cours.
     */
    function addPoint(x, y) {
        currentPoints.push({ x, y });

        const circle = new fabric.Circle({
            left: x - POINT_RADIUS,
            top: y - POINT_RADIUS,
            radius: POINT_RADIUS,
            fill: "rgba(255, 255, 255, 0.9)",
            stroke: "#333",
            strokeWidth: 1,
            selectable: false,
            evented: false,
        });
        fabricCanvas.add(circle);
        tempCircles.push(circle);

        if (currentPoints.length > 1) {
            const prev = currentPoints[currentPoints.length - 2];
            const line = new fabric.Line([prev.x, prev.y, x, y], {
                stroke: "rgba(255, 255, 255, 0.8)",
                strokeWidth: LINE_WIDTH,
                selectable: false,
                evented: false,
            });
            fabricCanvas.add(line);
            tempLines.push(line);
        }

        fabricCanvas.renderAll();
        setStatus(`Dessin en cours — ${currentPoints.length} point(s)`);
    }

    /**
     * Met à jour la ligne de prévisualisation.
     */
    function updatePreviewLine(opt) {
        const pointer = fabricCanvas.getPointer(opt.e);
        const lastPoint = currentPoints[currentPoints.length - 1];

        if (previewLine) {
            fabricCanvas.remove(previewLine);
        }

        previewLine = new fabric.Line(
            [lastPoint.x, lastPoint.y, pointer.x, pointer.y],
            {
                stroke: "rgba(255, 255, 255, 0.5)",
                strokeWidth: 1,
                strokeDashArray: [5, 5],
                selectable: false,
                evented: false,
            }
        );
        fabricCanvas.add(previewLine);
        fabricCanvas.renderAll();
    }

    /**
     * Ferme le polygone en cours.
     */
    function closePolygon() {
        // Nettoyer les éléments temporaires
        if (previewLine) {
            fabricCanvas.remove(previewLine);
            previewLine = null;
        }
        tempLines.forEach((l) => fabricCanvas.remove(l));
        tempCircles.forEach((c) => fabricCanvas.remove(c));

        const canvasPolygon = currentPoints.map((p) => [p.x, p.y]);
        const color = getNextColor();
        const name = getNextZoneName();
        const fabricObj = drawCompletedPolygon(canvasPolygon, color);

        completedZones.push({
            name: name,
            polygon: canvasPolygon,
            color: color,
            fabricObj: fabricObj,
        });

        // Réinitialiser l'état de dessin
        currentPoints = [];
        tempLines = [];
        tempCircles = [];
        isDrawing = false;

        updateZoneList();
        fabricCanvas.renderAll();
        setStatus(`Zone "${name}" créée — ${completedZones.length} zone(s) au total`);
    }

    /**
     * Annule le dessin en cours.
     */
    function cancelDrawing() {
        if (previewLine) {
            fabricCanvas.remove(previewLine);
            previewLine = null;
        }
        tempLines.forEach((l) => fabricCanvas.remove(l));
        tempCircles.forEach((c) => fabricCanvas.remove(c));

        currentPoints = [];
        tempLines = [];
        tempCircles = [];
        isDrawing = false;

        fabricCanvas.renderAll();
        setStatus("Dessin annulé");
    }

    /**
     * Dessine un polygone complété sur le canvas.
     */
    function drawCompletedPolygon(canvasPolygon, color) {
        const r = color[0], g = color[1], b = color[2];
        const fillColor = `rgba(${r}, ${g}, ${b}, ${FILL_OPACITY})`;
        const strokeColor = `rgb(${r}, ${g}, ${b})`;

        const points = canvasPolygon.map((p) => ({ x: p[0], y: p[1] }));
        const polygon = new fabric.Polygon(points, {
            fill: fillColor,
            stroke: strokeColor,
            strokeWidth: LINE_WIDTH + 1,
            selectable: false,
            evented: false,
            objectCaching: false,
        });
        fabricCanvas.add(polygon);
        return polygon;
    }

    // === Gestion des zones ===

    /**
     * Trouve l'index de la zone sous le point (x, y).
     * Retourne -1 si aucune zone n'est trouvée.
     */
    function findZoneAtPoint(x, y) {
        // Parcourir les zones en ordre inverse (la dernière dessinée est au-dessus)
        for (let i = completedZones.length - 1; i >= 0; i--) {
            const zone = completedZones[i];
            if (isPointInPolygon(x, y, zone.polygon)) {
                return i;
            }
        }
        return -1;
    }

    /**
     * Test point-in-polygon (ray casting).
     */
    function isPointInPolygon(x, y, polygon) {
        let inside = false;
        for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
            const xi = polygon[i][0], yi = polygon[i][1];
            const xj = polygon[j][0], yj = polygon[j][1];
            const intersect =
                yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
            if (intersect) inside = !inside;
        }
        return inside;
    }

    /**
     * Sélectionne une zone par son index.
     */
    function selectZone(idx) {
        deselectZone();
        selectedZoneIndex = idx;

        // Épaissir le contour de la zone sélectionnée
        const zone = completedZones[idx];
        if (zone.fabricObj) {
            zone.fabricObj.set({
                strokeWidth: LINE_WIDTH + 3,
                strokeDashArray: [8, 4],
            });
            fabricCanvas.renderAll();
        }

        updateZoneList();
        setStatus(`Zone "${zone.name}" sélectionnée — Suppr pour supprimer`);
    }

    /**
     * Désélectionne la zone courante.
     */
    function deselectZone() {
        if (selectedZoneIndex >= 0 && selectedZoneIndex < completedZones.length) {
            const zone = completedZones[selectedZoneIndex];
            if (zone.fabricObj) {
                zone.fabricObj.set({
                    strokeWidth: LINE_WIDTH + 1,
                    strokeDashArray: null,
                });
            }
        }
        selectedZoneIndex = -1;
        updateZoneList();
        fabricCanvas && fabricCanvas.renderAll();
    }

    /**
     * Supprime une zone par son index.
     */
    function deleteZone(idx) {
        if (idx < 0 || idx >= completedZones.length) return;
        const zone = completedZones[idx];

        // Supprimer l'objet Fabric du canvas
        if (zone.fabricObj) {
            fabricCanvas.remove(zone.fabricObj);
        }

        completedZones.splice(idx, 1);
        selectedZoneIndex = -1;

        // Renommer les zones restantes
        renumberZones();
        updateZoneList();
        fabricCanvas.renderAll();
        setStatus(`Zone supprimée — ${completedZones.length} zone(s) restante(s)`);
    }

    /**
     * Renumérote les zones après suppression.
     */
    function renumberZones() {
        completedZones.forEach((zone, i) => {
            zone.name = `zone${i + 1}_cam${camId}`;
        });
    }

    /**
     * Retourne la prochaine couleur de la palette.
     */
    function getNextColor() {
        return COLOR_PALETTE[completedZones.length % COLOR_PALETTE.length];
    }

    /**
     * Retourne le prochain nom de zone.
     */
    function getNextZoneName() {
        return `zone${completedZones.length + 1}_cam${camId}`;
    }

    // === Interface : liste des zones ===

    /**
     * Met à jour la liste des zones dans le panneau latéral.
     */
    function updateZoneList() {
        const container = $("zone-list");
        if (!container) return;

        if (completedZones.length === 0) {
            container.innerHTML =
                '<div style="color:#888;font-size:0.85rem;padding:8px;">Aucune zone définie</div>';
            return;
        }

        let html = "";
        completedZones.forEach((zone, i) => {
            const [r, g, b] = zone.color;
            const selected = i === selectedZoneIndex ? " selected" : "";
            const pts = zone.polygon.length;
            html += `
                <div class="zone-item${selected}" data-idx="${i}" onclick="zoneEditor.selectZone(${i})">
                    <span class="zone-color-dot" style="background:rgb(${r},${g},${b})"></span>
                    <span class="zone-item-name">${zone.name}</span>
                    <span class="zone-item-points">${pts}pts</span>
                    <button class="zone-item-delete" onclick="event.stopPropagation();zoneEditor.deleteZone(${i})" title="Supprimer">✕</button>
                </div>
            `;
        });
        container.innerHTML = html;
    }

    // === Boutons ===

    function setupButtons() {
        $("btn-save").addEventListener("click", saveZones);
        $("btn-reset").addEventListener("click", resetZones);
        $("btn-refresh").addEventListener("click", refreshSnapshot);
    }

    /**
     * Sauvegarde les zones vers le backend.
     */
    function saveZones() {
        if (completedZones.length === 0) {
            if (!confirm("Aucune zone définie. Sauvegarder supprimera toutes les zones existantes. Continuer ?")) {
                return;
            }
        }

        setStatus("Sauvegarde en cours...");
        showLoading(true);

        // Convertir les coordonnées canvas → réelles
        const zonesData = completedZones.map((zone) => ({
            name: zone.name,
            polygon: zone.polygon.map((pt) => [
                Math.round(pt[0] * scaleFactor),
                Math.round(pt[1] * scaleFactor),
            ]),
            color: zone.color,
        }));

        fetch(`/api/zones/${camId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ zones: zonesData }),
        })
            .then((res) => res.json())
            .then((data) => {
                showLoading(false);
                if (data.status === "ok") {
                    showToast(
                        `${data.zones_count} zone(s) sauvegardée(s) avec succès`,
                        "success"
                    );
                    setStatus(
                        `Sauvegardé — ${data.zones_count} zone(s) appliquées`,
                        "success"
                    );
                } else {
                    showToast("Erreur : " + data.message, "error");
                    setStatus("Erreur de sauvegarde", "error");
                }
            })
            .catch((err) => {
                showLoading(false);
                console.error("Erreur sauvegarde:", err);
                showToast("Erreur réseau", "error");
                setStatus("Erreur de sauvegarde", "error");
            });
    }

    /**
     * Réinitialise : recharge les zones depuis le backend.
     */
    function resetZones() {
        if (!confirm("Réinitialiser ? Les modifications non sauvegardées seront perdues.")) {
            return;
        }

        // Supprimer tous les objets du canvas sauf le fond
        fabricCanvas.getObjects().slice().forEach((obj) => fabricCanvas.remove(obj));
        cancelDrawing();
        completedZones = [];
        selectedZoneIndex = -1;

        loadExistingZones();
    }

    /**
     * Rafraîchit le snapshot (nouvelle capture).
     */
    function refreshSnapshot() {
        // Sauvegarder les zones actuelles en mémoire
        const savedZones = completedZones.map((z) => ({
            name: z.name,
            polygon: z.polygon.map((pt) => [...pt]),
            color: [...z.color],
        }));

        showLoading(true);
        setStatus("Rafraîchissement du snapshot...");

        const img = new Image();
        img.crossOrigin = "anonymous";

        img.onload = function () {
            imageWidth = img.naturalWidth;
            imageHeight = img.naturalHeight;

            if (imageWidth > MAX_CANVAS_WIDTH) {
                scaleFactor = imageWidth / MAX_CANVAS_WIDTH;
                canvasWidth = MAX_CANVAS_WIDTH;
                canvasHeight = Math.round(imageHeight / scaleFactor);
            } else {
                scaleFactor = 1;
                canvasWidth = imageWidth;
                canvasHeight = imageHeight;
            }

            initCanvas(img);

            // Redessiner les zones sauvegardées
            completedZones = [];
            savedZones.forEach((z) => {
                const fabricObj = drawCompletedPolygon(z.polygon, z.color);
                completedZones.push({
                    name: z.name,
                    polygon: z.polygon,
                    color: z.color,
                    fabricObj: fabricObj,
                });
            });

            updateZoneList();
            showLoading(false);
            setStatus(`Snapshot rafraîchi — ${completedZones.length} zone(s)`);
        };

        img.onerror = function () {
            showLoading(false);
            setStatus("Erreur de rafraîchissement", "error");
        };

        img.src = `/snapshot/${camId}?t=${Date.now()}`;
    }

    // === Utilitaires d'interface ===

    function updateImageInfo() {
        const infoEl = $("image-info");
        if (infoEl) {
            infoEl.textContent = `${imageWidth}×${imageHeight}px → affiché ${canvasWidth}×${canvasHeight}px (×${scaleFactor.toFixed(2)})`;
        }
    }

    function showLoading(visible) {
        const el = $("loading-overlay");
        if (el) {
            el.classList.toggle("hidden", !visible);
        }
    }

    function setStatus(message, type) {
        const el = $("status-message");
        if (el) {
            el.textContent = message;
            el.className = "status-message" + (type ? ` ${type}` : "");
        }
    }

    function showToast(message, type) {
        const toast = $("toast");
        if (!toast) return;
        toast.textContent = message;
        toast.className = `toast ${type || "info"} visible`;
        setTimeout(() => {
            toast.classList.remove("visible");
        }, 3000);
    }

    // === API publique (pour les onclick du HTML) ===
    window.zoneEditor = {
        selectZone: selectZone,
        deleteZone: deleteZone,
    };

    // Lancer au chargement
    document.addEventListener("DOMContentLoaded", init);
})();
