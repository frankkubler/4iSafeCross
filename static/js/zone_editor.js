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
    const HANDLE_RADIUS = 7;   // Rayon des poignées de sommet
    const PROJ_RADIUS = 18;    // Rayon des icônes de projecteur relais

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

    // Masques terminés : [{name, polygon (coords canvas), fabricObj}]
    let completedMasks = [];
    let selectedMaskIndex = -1;

    // Mode éditeur : 'zone' | 'mask'
    let editorMode = 'zone';

    // État de l'édition de sommets (poignées draggables)
    let editingIndex = -1;   // Index du polygone en édition (-1 = aucun)
    let editingType = null;  // 'zone' | 'mask'
    let editHandles = [];    // Poignées fabric.Circle
    let editEdges = [];      // Arêtes fabric.Line temporaires

    // Projecteurs relais — icônes draggables sur canvas
    let projectorIcons = {};   // {relayId: fabric.Group}
    let relayPositions = {};   // {relayId: {x, y}} — coordonnées canvas

    // État du dessin en cours
    let isDrawing = false;
    let currentPoints = [];
    let tempLines = [];
    let tempCircles = [];
    let previewLine = null;
    let isShiftDown = false;

    // === Éléments DOM ===
    const $ = (id) => document.getElementById(id);

    // === Initialisation ===
    function init() {
        camId = parseInt($("editor-canvas").dataset.camId, 10);

        setupButtons();
        loadSnapshot();
    }

    /**
     * Bascule entre le mode zones et le mode masques.
     */
    function toggleEditorMode() {
        editorMode = editorMode === 'zone' ? 'mask' : 'zone';
        const btn = $("btn-mode");
        if (editorMode === 'mask') {
            btn.textContent = '\u2b1b Mode : Masques';
            btn.classList.remove('btn-mode-zone');
            btn.classList.add('btn-mode-mask');
            $("instructions-zone").style.display = 'none';
            $("instructions-mask").style.display = '';
        } else {
            btn.textContent = '\ud83d\udccc Mode : Zones';
            btn.classList.remove('btn-mode-mask');
            btn.classList.add('btn-mode-zone');
            $("instructions-zone").style.display = '';
            $("instructions-mask").style.display = 'none';
        }
        // Annuler tout dessin en cours lors du changement de mode
        if (isDrawing) cancelDrawing();
        if (editingIndex >= 0) exitEditMode();
        deselectZone();
        deselectMask();
        setStatus(editorMode === 'mask' ? 'Mode masque actif — dessinez les zones exclues de la détection' : 'Mode zones actif');
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
            loadExistingMasks();
            projectorIcons = {};
            loadRelayPositions();
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
                        relays: zone.relays || [],
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

    /**
     * Charge les masques existants depuis l'API et les dessine sur le canvas.
     */
    function loadExistingMasks() {
        fetch(`/api/masks/${camId}`)
            .then((res) => res.json())
            .then((masks) => {
                completedMasks = [];
                masks.forEach((mask) => {
                    const canvasPolygon = mask.polygon.map((pt) => [
                        pt[0] / scaleFactor,
                        pt[1] / scaleFactor,
                    ]);
                    const fabricObj = drawMaskPolygon(canvasPolygon);
                    completedMasks.push({
                        name: mask.name,
                        polygon: canvasPolygon,
                        fabricObj: fabricObj,
                    });
                });
                updateZoneList();
            })
            .catch(() => {
                // Pas de masques définis — silencieux
            });
    }

    /**
     * Dessine un polygone masque sur le canvas (fond noir transparent, contour gris).
     */
    function drawMaskPolygon(canvasPolygon) {
        const points = canvasPolygon.map((p) => ({ x: p[0], y: p[1] }));
        const polygon = new fabric.Polygon(points, {
            fill: 'rgba(0, 0, 0, 0.6)',
            stroke: '#888888',
            strokeWidth: 2,
            strokeDashArray: [6, 3],
            selectable: false,
            evented: false,
            objectCaching: false,
        });
        fabricCanvas.add(polygon);
        return polygon;
    }

    // === Projecteurs relais ===

    /**
     * Charge les positions des projecteurs depuis le backend et les dessine.
     */
    function loadRelayPositions() {
        if (camId === null || camId === undefined) return;
        fetch(`/api/relay_positions/${camId}`)
            .then((r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then((data) => {
                relayPositions = {};
                Object.entries(data).forEach(([rid, coords]) => {
                    const realId = parseInt(rid, 10);
                    relayPositions[realId] = {
                        x: coords[0] / scaleFactor,
                        y: coords[1] / scaleFactor,
                    };
                });
                refreshProjectorIcons();
            })
            .catch((err) => {
                console.warn("Impossible de charger les positions relais :", err);
                relayPositions = {};
                refreshProjectorIcons();  // Afficher les icônes aux positions par défaut
            });
    }

    /**
     * Dessine une icône de projecteur pour le relais donné.
     * Retourne { body, label } — deux objets Fabric indépendants.
     */
    function drawProjectorIcon(relayId, cx, cy) {
        const body = new fabric.Circle({
            left: cx,
            top: cy,
            radius: PROJ_RADIUS,
            fill: '#1a1a2e',
            stroke: '#ffcc00',
            strokeWidth: 2,
            originX: 'center',
            originY: 'center',
            selectable: true,
            hasControls: false,
            hasBorders: false,
            evented: true,
            lockRotation: true,
            lockScalingX: true,
            lockScalingY: true,
        });
        body._relayId = relayId;

        const label = new fabric.Text(`R${relayId}`, {
            left: cx,
            top: cy + PROJ_RADIUS + 3,
            fontSize: 12,
            fill: '#ffffff',
            fontWeight: 'bold',
            originX: 'center',
            originY: 'top',
            selectable: false,
            evented: false,
        });

        fabricCanvas.add(body);
        fabricCanvas.add(label);
        body.setCoords();
        label.setCoords();
        fabricCanvas.bringToFront(body);
        fabricCanvas.bringToFront(label);
        console.log(`[Projecteur] R${relayId} ajouté à (${Math.round(cx)}, ${Math.round(cy)})`);
        return { body, label };
    }

    /**
     * Supprime toutes les icônes de projecteur du canvas.
     */
    function clearProjectorIcons() {
        Object.values(projectorIcons).forEach(({ body, label }) => {
            fabricCanvas.remove(body);
            fabricCanvas.remove(label);
        });
        projectorIcons = {};
    }

    /**
     * Recrée les icônes de projecteur à partir de relayPositions.
     * Crée des icônes par défaut (R0–R4) si non encore positionnées.
     */
    function refreshProjectorIcons() {
        clearProjectorIcons();
        console.log(`[Projecteur] refreshProjectorIcons — canvasWidth=${canvasWidth} canvasHeight=${canvasHeight}`);
        Object.entries(relayPositions).forEach(([rid, pos]) => {
            const relayId = parseInt(rid, 10);
            projectorIcons[relayId] = drawProjectorIcon(relayId, pos.x, pos.y);
        });
        const relayCount = (typeof NUM_RELAYS !== 'undefined' && NUM_RELAYS > 0) ? NUM_RELAYS : 5;
        for (let i = 0; i < relayCount; i++) {
            if (!projectorIcons[i]) {
                const defaultX = (canvasWidth / (relayCount + 1)) * (i + 1);
                const defaultY = PROJ_RADIUS + 10;   // haut du canvas
                relayPositions[i] = { x: defaultX, y: defaultY };
                projectorIcons[i] = drawProjectorIcon(i, defaultX, defaultY);
            }
        }
        updateProjectorHighlights();
        fabricCanvas.renderAll();
        console.log(`[Projecteur] ${Object.keys(projectorIcons).length} icônes dans fabricCanvas (${fabricCanvas.getObjects().length} objets total)`);
    }

    /**
     * Cherche un projecteur aux coordonnées données (retourne relayId ou -1).
     */
    function findProjectorAtPoint(x, y) {
        for (const [rid, { body }] of Object.entries(projectorIcons)) {
            const cx = body.left;
            const cy = body.top;
            const dx = x - cx;
            const dy = y - cy;
            if (Math.sqrt(dx * dx + dy * dy) <= PROJ_RADIUS + 4) {
                return parseInt(rid, 10);
            }
        }
        return -1;
    }

    /**
     * Met à jour la surbrillance des projecteurs selon la zone sélectionnée.
     */
    function updateProjectorHighlights() {
        if (!fabricCanvas) return;
        const activeRelays = new Set();
        if (selectedZoneIndex >= 0 && selectedZoneIndex < completedZones.length) {
            (completedZones[selectedZoneIndex].relays || []).forEach((r) => activeRelays.add(r));
        }
        Object.entries(projectorIcons).forEach(([rid]) => {
            highlightProjector(parseInt(rid, 10), activeRelays.has(parseInt(rid, 10)));
        });
        fabricCanvas.renderAll();
    }

    /**
     * Allume (lit=true) ou éteint un projecteur relais.
     */
    function highlightProjector(relayId, lit) {
        const icon = projectorIcons[relayId];
        if (!icon) return;
        if (lit) {
            icon.body.set({ fill: '#8a6a00', stroke: '#ffcc00' });
            icon.label.set({ fill: '#ffe066' });
        } else {
            icon.body.set({ fill: '#333333', stroke: '#888888' });
            icon.label.set({ fill: '#cccccc' });
        }
    }

    // === Événements canvas ===
    function setupCanvasEvents() {
        // Clic gauche : ajouter un point ou sélectionner une zone
        fabricCanvas.on("mouse:down", function (opt) {
            if (opt.e.button !== 0) return;
            const pointer = fabricCanvas.getPointer(opt.e);

            // Ignorer les clics sur les icônes de projecteur
            if (opt.target && opt.target._relayId !== undefined) return;

            // == Mode édition de sommets ==
            if (editingIndex >= 0) {
                // Clic sur une poignée → Fabric gère le drag automatiquement
                if (opt.target && opt.target._vertexIndex !== undefined) return;
                // Clic ailleurs → sortir du mode édition
                exitEditMode();
                return;
            }

            if (!isDrawing) {
                // Vérifier si on clique sur une zone existante
                const clickedZoneIdx = findZoneAtPoint(pointer.x, pointer.y);
                if (editorMode === 'mask') {
                    // En mode masque, chercher d'abord un masque existant
                    const clickedMaskIdx = findMaskAtPoint(pointer.x, pointer.y);
                    if (clickedMaskIdx >= 0) {
                        selectMask(clickedMaskIdx);
                        return;
                    }
                } else {
                    if (clickedZoneIdx >= 0) {
                        selectZone(clickedZoneIdx);
                        return;
                    }
                }
                // Sinon démarrer un nouveau polygone
                isDrawing = true;
                if (editorMode === 'mask') deselectMask(); else deselectZone();
            }

            // Snap aux bords
            let x = snapToBorder(pointer.x, canvasWidth);
            let y = snapToBorder(pointer.y, canvasHeight);

            // Shift : contraindre aux axes cardinaux par rapport au dernier point
            if (isShiftDown && currentPoints.length > 0) {
                const constrained = constrainToCardinalAxes(
                    currentPoints[currentPoints.length - 1],
                    { x, y }
                );
                x = constrained.x;
                y = constrained.y;
            }

            addPoint(x, y);
        });

        // Clic droit : fermer le polygone
        fabricCanvas.upperCanvasEl.addEventListener("contextmenu", function (e) {
            e.preventDefault();
            if (isDrawing && currentPoints.length >= 3) {
                closePolygon();
            }
        });

        // Double-clic : entrer en mode édition des sommets
        // (dblclick se déclenche après les deux mousedown, sans conflit de garde)
        fabricCanvas.upperCanvasEl.addEventListener("dblclick", function (e) {
            e.preventDefault();
            if (isDrawing || editingIndex >= 0) return;
            const pointer = fabricCanvas.getPointer(e);
            if (findProjectorAtPoint(pointer.x, pointer.y) >= 0) return;
            if (editorMode === 'mask') {
                const idx = findMaskAtPoint(pointer.x, pointer.y);
                if (idx >= 0) enterEditMode(idx, 'mask');
            } else {
                const idx = findZoneAtPoint(pointer.x, pointer.y);
                if (idx >= 0) enterEditMode(idx, 'zone');
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

        // Touche Suppr : supprimer la zone ou le masque sélectionné
        document.addEventListener("keydown", function (e) {
            if (e.key === "Shift") {
                isShiftDown = true;
            }
            if (e.key === "Delete") {
                if (editorMode === 'mask' && selectedMaskIndex >= 0) {
                    deleteMask(selectedMaskIndex);
                } else if (editorMode === 'zone' && selectedZoneIndex >= 0) {
                    deleteZone(selectedZoneIndex);
                }
            }
            // Échap : annuler le dessin ou sortir du mode édition
            if (e.key === "Escape") {
                if (editingIndex >= 0) {
                    exitEditMode();
                } else if (isDrawing) {
                    cancelDrawing();
                }
            }
        });

        document.addEventListener("keyup", function (e) {
            if (e.key === "Shift") {
                isShiftDown = false;
            }
        });

        // Déplacement d'une poignée de sommet ou d'un projecteur
        fabricCanvas.on("object:moving", function (opt) {
            if (opt.target && opt.target._relayId !== undefined) {
                const rid = opt.target._relayId;
                relayPositions[rid] = { x: opt.target.left, y: opt.target.top };
                const icon = projectorIcons[rid];
                if (icon && icon.label) {
                    icon.label.set({
                        left: opt.target.left,
                        top: opt.target.top + PROJ_RADIUS + 4,
                    });
                    icon.label.setCoords();
                }
                return;
            }
            if (editingIndex < 0 || !opt.target || opt.target._vertexIndex === undefined) return;
            const handle = opt.target;
            const i = handle._vertexIndex;
            // La position left/top est le coin supérieur gauche du cercle
            const x = handle.left + HANDLE_RADIUS;
            const y = handle.top + HANDLE_RADIUS;
            const item = editingType === 'zone'
                ? completedZones[editingIndex]
                : completedMasks[editingIndex];
            item.polygon[i] = [x, y];
            updateEditEdges();
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
     * Contraint un point aux axes cardinaux (H ou V) par rapport à l'origine.
     */
    function constrainToCardinalAxes(origin, point) {
        const dx = Math.abs(point.x - origin.x);
        const dy = Math.abs(point.y - origin.y);
        if (dx >= dy) {
            // Axe horizontal
            return { x: point.x, y: origin.y };
        } else {
            // Axe vertical
            return { x: origin.x, y: point.y };
        }
    }

    /**
     * Met à jour la ligne de prévisualisation.
     */
    function updatePreviewLine(opt) {
        const pointer = fabricCanvas.getPointer(opt.e);
        const lastPoint = currentPoints[currentPoints.length - 1];

        // Shift : contraindre aux axes cardinaux
        let targetX = pointer.x;
        let targetY = pointer.y;
        if (isShiftDown) {
            const constrained = constrainToCardinalAxes(lastPoint, { x: targetX, y: targetY });
            targetX = constrained.x;
            targetY = constrained.y;
        }

        if (previewLine) {
            fabricCanvas.remove(previewLine);
        }

        previewLine = new fabric.Line(
            [lastPoint.x, lastPoint.y, targetX, targetY],
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

        if (editorMode === 'mask') {
            const name = getNextMaskName();
            const fabricObj = drawMaskPolygon(canvasPolygon);
            completedMasks.push({ name, polygon: canvasPolygon, fabricObj });
            currentPoints = []; tempLines = []; tempCircles = []; isDrawing = false;
            updateZoneList();
            fabricCanvas.renderAll();
            setStatus(`Masque "${name}" créé — ${completedMasks.length} masque(s) au total`);
            return;
        }

        const color = getNextColor();
        const name = getNextZoneName();
        const fabricObj = drawCompletedPolygon(canvasPolygon, color);

        completedZones.push({
            name: name,
            polygon: canvasPolygon,
            color: color,
            relays: [],
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

    // === Édition de sommets (poignées draggables) ===

    /**
     * Entre en mode édition de sommets pour un polygone (zone ou masque).
     * Affiche des poignées circulaires draggables sur chaque sommet.
     * Déclenché par un deuxième clic sur un polygone déjà sélectionné.
     */
    function enterEditMode(idx, type) {
        exitEditMode();  // Sortir d'un éventuel mode édition précédent
        editingIndex = idx;
        editingType = type;
        const item = type === 'zone' ? completedZones[idx] : completedMasks[idx];
        const poly = item.polygon;

        // Réduire l'opacité du polygone d'origine pour laisser les poignées visibles
        if (item.fabricObj) item.fabricObj.set({ opacity: 0.25 });

        // Couleurs selon le type
        const edgeColor = type === 'zone'
            ? `rgb(${item.color[0]},${item.color[1]},${item.color[2]})`
            : '#aaaaaa';
        const handleFill = type === 'zone'
            ? `rgba(${item.color[0]},${item.color[1]},${item.color[2]},0.9)`
            : 'rgba(220,220,220,0.9)';

        // Dessiner les arêtes temporaires (sous les poignées)
        for (let i = 0; i < poly.length; i++) {
            const j = (i + 1) % poly.length;
            const line = new fabric.Line(
                [poly[i][0], poly[i][1], poly[j][0], poly[j][1]],
                {
                    stroke: edgeColor,
                    strokeWidth: 2,
                    strokeDashArray: [5, 3],
                    selectable: false,
                    evented: false,
                    objectCaching: false,
                }
            );
            fabricCanvas.add(line);
            editEdges.push(line);
        }

        // Dessiner les poignées (une par sommet)
        for (let i = 0; i < poly.length; i++) {
            const handle = new fabric.Circle({
                left: poly[i][0] - HANDLE_RADIUS,
                top: poly[i][1] - HANDLE_RADIUS,
                radius: HANDLE_RADIUS,
                fill: handleFill,
                stroke: '#ffffff',
                strokeWidth: 2,
                selectable: true,
                evented: true,
                hasBorders: false,
                hasControls: false,
                originX: 'left',
                originY: 'top',
                objectCaching: false,
            });
            handle._vertexIndex = i;
            fabricCanvas.add(handle);
            editHandles.push(handle);
        }

        fabricCanvas.hoverCursor = 'default';
        fabricCanvas.defaultCursor = 'default';
        fabricCanvas.renderAll();
        setStatus(
            `Édition de "${item.name}" — glissez les poignées · Échap pour terminer`
        );
    }

    /**
     * Nettoie les poignées et arêtes temporaires sans redessiner le polygone.
     * Utilisé en interne avant une suppression ou un reset.
     */
    function _cleanEditState() {
        editHandles.forEach((h) => fabricCanvas.remove(h));
        editEdges.forEach((e) => fabricCanvas.remove(e));
        editHandles = [];
        editEdges = [];
        editingIndex = -1;
        editingType = null;
        fabricCanvas.hoverCursor = 'crosshair';
        fabricCanvas.defaultCursor = 'crosshair';
    }

    /**
     * Quitte le mode édition : redessine le polygone avec les coordonnées mises à jour.
     */
    function exitEditMode() {
        if (editingIndex < 0) return;
        const idx = editingIndex;
        const type = editingType;
        const item = type === 'zone' ? completedZones[idx] : completedMasks[idx];
        _cleanEditState();

        // Supprimer l'ancien objet fantôme et redessiner avec les coords mises à jour
        if (item.fabricObj) fabricCanvas.remove(item.fabricObj);
        item.fabricObj = type === 'zone'
            ? drawCompletedPolygon(item.polygon, item.color)
            : drawMaskPolygon(item.polygon);

        fabricCanvas.renderAll();
        setStatus('Édition terminée');
    }

    /**
     * Redessine les arêtes temporaires en temps réel pendant le déplacement des poignées.
     */
    function updateEditEdges() {
        const item = editingType === 'zone'
            ? completedZones[editingIndex]
            : completedMasks[editingIndex];
        const poly = item.polygon;
        editEdges.forEach((line, i) => {
            const j = (i + 1) % poly.length;
            line.set({ x1: poly[i][0], y1: poly[i][1], x2: poly[j][0], y2: poly[j][1] });
        });
        fabricCanvas.renderAll();
    }

    // === Gestion des zones ===

    /**
     * Trouve l'index de la zone sous le point (x, y).
     * Retourne -1 si aucune zone n'est trouvée.
     */
    function findZoneAtPoint(x, y) {
        for (let i = completedZones.length - 1; i >= 0; i--) {
            if (isPointInPolygon(x, y, completedZones[i].polygon)) return i;
        }
        return -1;
    }

    /**
     * Trouve l'index du masque sous le point (x, y).
     * Retourne -1 si aucun masque n'est trouvé.
     */
    function findMaskAtPoint(x, y) {
        for (let i = completedMasks.length - 1; i >= 0; i--) {
            if (isPointInPolygon(x, y, completedMasks[i].polygon)) return i;
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
        deselectMask();
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
        updateProjectorHighlights();
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
        updateProjectorHighlights();
    }

    /**
     * Sélectionne un masque par son index.
     */
    function selectMask(idx) {
        deselectMask();
        deselectZone();
        selectedMaskIndex = idx;
        const mask = completedMasks[idx];
        if (mask && mask.fabricObj) {
            mask.fabricObj.set({ strokeWidth: 3, stroke: '#fff' });
            fabricCanvas.renderAll();
        }
        updateZoneList();
        setStatus(`Masque "${mask.name}" sélectionné — Suppr pour supprimer`);
    }

    /**
     * Désélectionne le masque courant.
     */
    function deselectMask() {
        if (selectedMaskIndex >= 0 && selectedMaskIndex < completedMasks.length) {
            const mask = completedMasks[selectedMaskIndex];
            if (mask && mask.fabricObj) {
                mask.fabricObj.set({ strokeWidth: 2, stroke: '#888888' });
            }
        }
        selectedMaskIndex = -1;
        updateZoneList();
        fabricCanvas && fabricCanvas.renderAll();
    }

    /**
     * Supprime un masque par son index.
     */
    function deleteMask(idx) {
        if (idx < 0 || idx >= completedMasks.length) return;
        // Si ce masque est en cours d'édition, nettoyer sans redessiner
        if (editingIndex === idx && editingType === 'mask') _cleanEditState();
        const mask = completedMasks[idx];
        if (mask.fabricObj) fabricCanvas.remove(mask.fabricObj);
        completedMasks.splice(idx, 1);
        selectedMaskIndex = -1;
        renumberMasks();
        updateZoneList();
        fabricCanvas.renderAll();
        setStatus(`Masque supprimé — ${completedMasks.length} masque(s) restant(s)`);
    }

    /**
     * Renumérote les masques après suppression.
     */
    function renumberMasks() {
        completedMasks.forEach((mask, i) => {
            mask.name = `mask${i + 1}_cam${camId}`;
        });
    }

    /**
     * Retourne le prochain nom de masque.
     */
    function getNextMaskName() {
        return `mask${completedMasks.length + 1}_cam${camId}`;
    }

    /**
     * Supprime une zone par son index.
     */
    function deleteZone(idx) {
        if (idx < 0 || idx >= completedZones.length) return;
        // Si cette zone est en cours d'édition, nettoyer sans redessiner
        if (editingIndex === idx && editingType === 'zone') _cleanEditState();
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

        let html = "";

        // ---- Section Zones ----
        html += `<div class="list-section-title">Zones détection (${completedZones.length})</div>`;
        if (completedZones.length === 0) {
            html += '<div style="color:#888;font-size:0.85rem;padding:4px 8px;">Aucune zone définie</div>';
        } else {
            completedZones.forEach((zone, i) => {
                const [r, g, b] = zone.color;
                const selected = i === selectedZoneIndex ? " selected" : "";
                const pts = zone.polygon.length;
                const numRelays = typeof NUM_RELAYS !== 'undefined' ? NUM_RELAYS : 0;
                let relayCheckboxes = '';
                if (numRelays > 0) {
                    let checkboxHtml = '';
                    for (let rn = 0; rn < numRelays; rn++) {
                        const checked = (zone.relays || []).includes(rn) ? 'checked' : '';
                        checkboxHtml += `<label class="relay-cb" title="Relais ${rn}">
                            <input type="checkbox" ${checked} onchange="zoneEditor.toggleRelay(${i}, ${rn})">
                            <span>${rn}</span>
                        </label>`;
                    }
                    relayCheckboxes = `<div class="zone-relays" onclick="event.stopPropagation()"><span class="zone-relays-label">Relais :</span>${checkboxHtml}</div>`;
                }
                html += `
                    <div class="zone-item${selected}" data-idx="${i}" onclick="zoneEditor.selectZone(${i})">
                        <div class="zone-item-header">
                            <span class="zone-color-dot" style="background:rgb(${r},${g},${b})"></span>
                            <span class="zone-item-name">${zone.name}</span>
                            <span class="zone-item-points">${pts}pts</span>
                            <button class="zone-item-delete" onclick="event.stopPropagation();zoneEditor.deleteZone(${i})" title="Supprimer">✕</button>
                        </div>
                        ${relayCheckboxes}
                    </div>
                `;
            });
        }

        // ---- Section Masques ----
        html += `<div class="list-section-title mask-section-title">⬛ Masques (${completedMasks.length})</div>`;
        if (completedMasks.length === 0) {
            html += '<div style="color:#888;font-size:0.85rem;padding:4px 8px;">Aucun masque défini</div>';
        } else {
            completedMasks.forEach((mask, i) => {
                const selected = i === selectedMaskIndex ? " selected" : "";
                const pts = mask.polygon.length;
                html += `
                    <div class="zone-item mask-item${selected}" data-midx="${i}" onclick="zoneEditor.selectMask(${i})">
                        <div class="zone-item-header">
                            <span class="zone-color-dot mask-color-dot"></span>
                            <span class="zone-item-name">${mask.name}</span>
                            <span class="zone-item-points">${pts}pts</span>
                            <button class="zone-item-delete" onclick="event.stopPropagation();zoneEditor.deleteMask(${i})" title="Supprimer">✕</button>
                        </div>
                    </div>
                `;
            });
        }

        container.innerHTML = html;
    }

    // === Boutons ===

    function setupButtons() {
        $("btn-save").addEventListener("click", saveZones);
        $("btn-reset").addEventListener("click", resetZones);
        $("btn-refresh").addEventListener("click", refreshSnapshot);
        $("btn-mode").addEventListener("click", toggleEditorMode);
    }

    /**
     * Sauvegarde les zones et les masques vers le backend.
     */
    function saveZones() {
        const hasZones = completedZones.length > 0;
        const hasMasks = completedMasks.length > 0;
        if (!hasZones && !hasMasks) {
            if (!confirm("Aucune zone ni masque défini. Sauvegarder supprimera toutes les configurations existantes. Continuer ?")) {
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
            relays: zone.relays || [],
        }));

        const masksData = completedMasks.map((mask) => ({
            name: mask.name,
            polygon: mask.polygon.map((pt) => [
                Math.round(pt[0] * scaleFactor),
                Math.round(pt[1] * scaleFactor),
            ]),
        }));

        const saveZonesReq = fetch(`/api/zones/${camId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ zones: zonesData }),
        }).then((res) => res.json());

        const saveMasksReq = fetch(`/api/masks/${camId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ masks: masksData }),
        }).then((res) => res.json());

        const relayPosData = {};
        Object.entries(relayPositions).forEach(([rid, pos]) => {
            relayPosData[rid] = [
                Math.round(pos.x * scaleFactor),
                Math.round(pos.y * scaleFactor),
            ];
        });
        const saveRelayPosReq = fetch(`/api/relay_positions/${camId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ positions: relayPosData }),
        }).then((res) => res.json());

        Promise.all([saveZonesReq, saveMasksReq, saveRelayPosReq])
            .then(([zData, mData]) => {
                showLoading(false);
                const zOk = zData.status === "ok";
                const mOk = mData.status === "ok";
                if (zOk && mOk) {
                    showToast(
                        `${zData.zones_count} zone(s) et ${mData.masks_count} masque(s) sauvegardé(s)`,
                        "success"
                    );
                    setStatus(`Sauvegardé — ${zData.zones_count} zone(s), ${mData.masks_count} masque(s)`, "success");
                } else {
                    const err = (!zOk ? zData.message : '') || (!mOk ? mData.message : '');
                    showToast("Erreur : " + err, "error");
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
     * Réinitialise : recharge les zones et les masques depuis le backend.
     */
    function resetZones() {
        if (!confirm("Réinitialiser ? Les modifications non sauvegardées seront perdues.")) {
            return;
        }

        // Supprimer tous les objets du canvas sauf le fond
        fabricCanvas.getObjects().slice().forEach((obj) => fabricCanvas.remove(obj));
        cancelDrawing();
        editingIndex = -1; editingType = null; editHandles = []; editEdges = [];
        completedZones = [];
        completedMasks = [];
        selectedZoneIndex = -1;
        selectedMaskIndex = -1;

        loadExistingZones();
        loadExistingMasks();
        projectorIcons = {};
        loadRelayPositions();
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
            relays: [...(z.relays || [])],
        }));
        const savedMasks = completedMasks.map((m) => ({
            name: m.name,
            polygon: m.polygon.map((pt) => [...pt]),
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
                    relays: z.relays || [],
                    fabricObj: fabricObj,
                });
            });

            // Redessiner les masques sauvegardés
            completedMasks = [];
            savedMasks.forEach((m) => {
                const fabricObj = drawMaskPolygon(m.polygon);
                completedMasks.push({ name: m.name, polygon: m.polygon, fabricObj });
            });

            projectorIcons = {};
            refreshProjectorIcons();
            updateZoneList();
            showLoading(false);
            setStatus(`Snapshot rafraîchi — ${completedZones.length} zone(s), ${completedMasks.length} masque(s)`);
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

    /**
     * Bascule l'activation d'un relais pour une zone.
     */
    function toggleRelay(zoneIdx, relayNum) {
        const zone = completedZones[zoneIdx];
        if (!zone) return;
        const idx = zone.relays.indexOf(relayNum);
        if (idx >= 0) {
            zone.relays.splice(idx, 1);
        } else {
            zone.relays.push(relayNum);
            zone.relays.sort((a, b) => a - b);
        }
        updateZoneList();
        updateProjectorHighlights();
    }

    // === API publique (pour les onclick du HTML) ===
    window.zoneEditor = {
        selectZone: selectZone,
        deleteZone: deleteZone,
        toggleRelay: toggleRelay,
        selectMask: selectMask,
        deleteMask: deleteMask,
    };

    // Lancer au chargement
    document.addEventListener("DOMContentLoaded", init);
})();
