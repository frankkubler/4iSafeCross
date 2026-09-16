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
    let projectorIcons = {};   // {relayId: {body, label}}
    let relayPositions = {};   // {relayId: {x, y}} — coordonnées canvas
    let movedRelayIds = new Set();    // Relais déplacés depuis le chargement
    let placedRelayIds = new Set();   // Relais posés sur le plan (les autres sont « disponibles »)
    let removedRelayIds = new Set();  // Relais retirés du plan : leur position doit être supprimée

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
                        skip_keypoint_filter: zone.skip_keypoint_filter || false,
                        debounce_frames: zone.debounce_frames != null ? zone.debounce_frames : null,
                        debounce_reset_seconds: zone.debounce_reset_seconds != null ? zone.debounce_reset_seconds : null,
                        fabricObj: fabricObj,
                    });
                });

                updateZoneList();
                // Les positions peuvent être déjà chargées (ordre des requêtes non
                // garanti) : dériver maintenant, et loadRelayPositions le refera.
                recomputeRelayAssignments();
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
                // Les masques sont opaques à 60 % : sans cela, un projecteur posé
                // sous un masque disparaîtrait de l'écran.
                bringProjectorsToFront();
                fabricCanvas.renderAll();
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
                placedRelayIds = new Set();
                removedRelayIds = new Set();
                Object.entries(data).forEach(([rid, coords]) => {
                    const realId = parseInt(rid, 10);
                    relayPositions[realId] = {
                        x: coords[0] / scaleFactor,
                        y: coords[1] / scaleFactor,
                    };
                    placedRelayIds.add(realId);   // une position enregistrée = projecteur posé
                });
                refreshProjectorIcons();
                recomputeRelayAssignments();
                checkRelayMismatch();
            })
            .catch((err) => {
                console.warn("Impossible de charger les positions relais :", err);
                relayPositions = {};
                placedRelayIds = new Set();
                movedRelayIds.clear();
                removedRelayIds.clear();
                refreshProjectorIcons();   // aucun projecteur posé : tous « disponibles »
            });
    }

    /**
     * Dessine une icône de projecteur pour le relais donné.
     * Retourne { body, label } — deux objets Fabric indépendants.
     */
    function drawProjectorIcon(relayId, cx, cy) {
        // Pastille pleine avec le numéro AU CENTRE, liseré sombre et ombre portée :
        // l'icône doit rester lisible sur une image de caméra quelconque et sous le
        // remplissage semi-transparent d'une zone. L'ancienne version (disque sombre,
        // numéro dessous, gris #333 dès qu'aucune zone n'était sélectionnée) devenait
        // invisible dans une zone colorée.
        const body = new fabric.Circle({
            left: cx,
            top: cy,
            radius: PROJ_RADIUS,
            fill: '#ffcc00',
            stroke: '#101019',
            strokeWidth: 3,
            originX: 'center',
            originY: 'center',
            selectable: true,
            hasControls: false,
            hasBorders: false,
            evented: true,
            lockRotation: true,
            lockScalingX: true,
            lockScalingY: true,
            shadow: new fabric.Shadow({ color: 'rgba(0,0,0,0.65)', blur: 6, offsetX: 0, offsetY: 2 }),
            hoverCursor: 'move',
        });
        body._relayId = relayId;

        const label = new fabric.Text(`${relayId}`, {
            left: cx,
            top: cy,
            fontSize: 17,
            fill: '#101019',
            fontWeight: 'bold',
            fontFamily: 'Arial, sans-serif',
            originX: 'center',
            originY: 'center',
            selectable: false,
            evented: false,
        });

        // Retrait du plan : pastille rouge avec une croix, plutôt qu'un emoji dont le
        // rendu dépend des polices du poste. Visible en permanence — un bouton de
        // sûreté doit être découvrable sans survol, peu fiable au doigt.
        const trashOffset = PROJ_RADIUS - 1;
        const trashBg = new fabric.Circle({
            left: cx + trashOffset,
            top: cy - trashOffset,
            radius: 9,
            fill: '#b91c1c',
            stroke: '#ffffff',
            strokeWidth: 2,
            originX: 'center',
            originY: 'center',
            selectable: false,
            evented: true,
            hoverCursor: 'pointer',
        });
        const trashMark = new fabric.Text('✕', {
            left: cx + trashOffset,
            top: cy - trashOffset,
            fontSize: 11,
            fill: '#ffffff',
            fontWeight: 'bold',
            fontFamily: 'Arial, sans-serif',
            originX: 'center',
            originY: 'center',
            selectable: false,
            evented: true,
            hoverCursor: 'pointer',
        });
        trashBg._removeRelayId = relayId;
        trashMark._removeRelayId = relayId;

        fabricCanvas.add(body);
        fabricCanvas.add(label);
        fabricCanvas.add(trashBg);
        fabricCanvas.add(trashMark);
        [body, label, trashBg, trashMark].forEach((o) => { o.setCoords(); fabricCanvas.bringToFront(o); });
        return { body, label, trash: trashBg, trashMark };
    }

    /**
     * Supprime toutes les icônes de projecteur du canvas.
     */
    function clearProjectorIcons() {
        Object.values(projectorIcons).forEach(({ body, label, trash, trashMark }) => {
            [body, label, trash, trashMark].forEach((o) => { if (o) fabricCanvas.remove(o); });
        });
        projectorIcons = {};
    }

    /**
     * Recrée les icônes des projecteurs POSÉS sur le plan.
     *
     * Un projecteur sans position enregistrée n'est plus placé d'office : il reste
     * « disponible » dans le panneau latéral. Poser une icône vaut affectation (le
     * centre fait foi), donc en placer d'office cinq au bord de l'image les aurait
     * affectés à toute zone touchant ce bord.
     */
    function refreshProjectorIcons() {
        clearProjectorIcons();
        placedRelayIds.forEach((relayId) => {
            const pos = relayPositions[relayId];
            if (pos) projectorIcons[relayId] = drawProjectorIcon(relayId, pos.x, pos.y);
        });
        updateProjectorHighlights();
        updateRelayStock();
        fabricCanvas.renderAll();
    }

    /**
     * Affecte les relais aux zones d'après la position de leur icône.
     *
     * Le centre de l'icône fait foi : un projecteur déclenche TOUTES les zones qui
     * le contiennent, ce qui permet le multi-zones sur une même caméra dès lors que
     * les zones se chevauchent — sans dupliquer l'icône ni la position. Même règle
     * géométrique que pour décider qu'un piéton est dans une zone
     * (src/core/geometry.point_in_zone).
     */
    function recomputeRelayAssignments() {
        // Un projecteur réputé posé mais sans position ne serait ni dessiné ni
        // proposé au stock : il disparaîtrait de l'interface. On le remet au stock.
        Array.from(placedRelayIds).forEach((relayId) => {
            if (!relayPositions[relayId]) {
                console.warn(`[Projecteur] R${relayId} posé sans position : remis dans les disponibles`);
                placedRelayIds.delete(relayId);
            }
        });
        completedZones.forEach((zone) => {
            zone.relays = [];
            placedRelayIds.forEach((relayId) => {
                const pos = relayPositions[relayId];
                if (pos && isPointInPolygon(pos.x, pos.y, zone.polygon)) {
                    zone.relays.push(relayId);
                }
            });
            zone.relays.sort((a, b) => a - b);
        });
        // Trace de diagnostic : position de chaque projecteur et zones déduites.
        if (placedRelayIds.size) {
            console.log('[Projecteur] affectations :', Array.from(placedRelayIds).sort().map((r) => {
                const p = relayPositions[r];
                const zs = completedZones.filter((z) => (z.relays || []).includes(r)).map((z) => z.name);
                return `R${r} (${Math.round(p.x)},${Math.round(p.y)}) → ${zs.length ? zs.join('+') : 'aucune zone'}`;
            }).join('  |  '));
        }
        updateZoneList();
        updateRelayStock();
        updateProjectorHighlights();
    }

    /**
     * Panneau « Projecteurs disponibles » : ceux qui ne sont pas posés sur le plan.
     */
    function updateRelayStock() {
        const box = $("relay-stock");
        if (!box) return;
        const relayCount = (typeof NUM_RELAYS !== 'undefined' && NUM_RELAYS > 0) ? NUM_RELAYS : 5;
        let html = "";
        for (let i = 0; i < relayCount; i++) {
            if (!placedRelayIds.has(i)) {
                html += `<span class="relay-chip" title="Poser le projecteur R${i} au centre du plan"
                              onclick="zoneEditor.placeRelay(${i})">⊙ R${i}</span>`;
            }
        }
        box.innerHTML = html;
    }

    /**
     * Pose un projecteur au centre du plan : à glisser ensuite dans une zone.
     */
    function placeRelay(relayId) {
        if (placedRelayIds.has(relayId)) return;
        relayPositions[relayId] = { x: canvasWidth / 2, y: canvasHeight / 2 };
        placedRelayIds.add(relayId);
        movedRelayIds.add(relayId);
        removedRelayIds.delete(relayId);
        refreshProjectorIcons();
        recomputeRelayAssignments();
        setStatus(`Projecteur R${relayId} posé au centre — le glisser dans une zone pour l'affecter`);
    }

    /**
     * Retire un projecteur du plan (corbeille) : il redevient « disponible » et
     * n'affecte plus aucune zone. Sa position sera supprimée à la sauvegarde.
     */
    function removeRelay(relayId) {
        if (!placedRelayIds.has(relayId)) return;
        const zonesConcernees = completedZones
            .filter((z) => (z.relays || []).includes(relayId))
            .map((z) => z.name);
        placedRelayIds.delete(relayId);
        movedRelayIds.delete(relayId);
        removedRelayIds.add(relayId);
        delete relayPositions[relayId];
        refreshProjectorIcons();
        recomputeRelayAssignments();
        setStatus(zonesConcernees.length
            ? `Projecteur R${relayId} retiré — n'est plus affecté à ${zonesConcernees.join(', ')}`
            : `Projecteur R${relayId} retiré du plan`);
    }

    /**
     * Compare les relais déclarés dans zones.ini aux relais dérivés des positions.
     * Une configuration antérieure peut déclarer un relais dans une zone tout en
     * ayant posé son icône ailleurs : la sauvegarde le retirerait silencieusement.
     */
    function checkRelayMismatch() {
        const box = $("relay-mismatch");
        if (!box || camId === null || camId === undefined) return;
        fetch(`/api/zone_relay_check/${camId}`)
            .then((r) => r.json())
            .then((data) => {
                const ecarts = data.mismatches || [];
                box.hidden = ecarts.length === 0;
                if (!ecarts.length) return;
                box.innerHTML =
                    `<strong>⚠️ ${ecarts.length} zone(s) : relais déclarés ≠ position des projecteurs.</strong><br>` +
                    ecarts.map((e) => {
                        const perdus = e.perdus.length ? `perdrait R${e.perdus.join(', R')}` : '';
                        const gagnes = e.gagnes.length ? `gagnerait R${e.gagnes.join(', R')}` : '';
                        return `${e.zone} : ${[perdus, gagnes].filter(Boolean).join(', ')}`;
                    }).join('<br>') +
                    `<br>L'affectation suit désormais la position de l'icône. Vérifier avant d'enregistrer.`;
            })
            .catch(() => { box.hidden = true; });
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
        // Projecteurs affectés à au moins une zone, toutes zones confondues.
        const assignedRelays = new Set();
        completedZones.forEach((z) => (z.relays || []).forEach((r) => assignedRelays.add(r)));
        Object.entries(projectorIcons).forEach(([rid]) => {
            const id = parseInt(rid, 10);
            highlightProjector(id, activeRelays.has(id), assignedRelays.has(id));
        });
        bringProjectorsToFront();
        fabricCanvas.renderAll();
    }

    /**
     * Allume (lit=true) ou éteint un projecteur relais.
     */
    /**
     * État visuel d'un projecteur.
     *
     * `lit`      : la zone sélectionnée le déclenche → cerclé de blanc.
     * `assigned` : posé dans au moins une zone → pastille jaune pleine.
     *              Sinon pastille sombre à liseré jaune : posé sur le plan mais
     *              n'allumant rien. Les deux états restent lisibles sur n'importe
     *              quelle image — l'ancien gris #333/#888 disparaissait sous le
     *              remplissage d'une zone.
     */
    function highlightProjector(relayId, lit, assigned) {
        const icon = projectorIcons[relayId];
        if (!icon) return;
        if (assigned) {
            icon.body.set({ fill: '#ffcc00', stroke: lit ? '#ffffff' : '#101019', strokeWidth: lit ? 4 : 3 });
            icon.label.set({ fill: '#101019' });
        } else {
            icon.body.set({ fill: '#2a2a3e', stroke: lit ? '#ffffff' : '#ffcc00', strokeWidth: lit ? 4 : 3 });
            icon.label.set({ fill: '#ffcc00' });
        }
    }

    /**
     * Ramène les projecteurs au premier plan.
     *
     * Fabric rend dans l'ordre d'ajout : les polygones de zones et de masques, dessinés
     * après le chargement des positions, recouvraient les icônes — un projecteur posé
     * dans une zone devenait invisible.
     */
    function bringProjectorsToFront() {
        Object.values(projectorIcons).forEach(({ body, label, trash, trashMark }) => {
            [body, label, trash, trashMark].forEach((o) => { if (o) fabricCanvas.bringToFront(o); });
        });
    }

    // === Événements canvas ===
    function setupCanvasEvents() {
        // Clic gauche : ajouter un point ou sélectionner une zone
        fabricCanvas.on("mouse:down", function (opt) {
            if (opt.e.button !== 0) return;
            const pointer = fabricCanvas.getPointer(opt.e);

            // Corbeille d'un projecteur : le retirer du plan
            if (opt.target && opt.target._removeRelayId !== undefined) {
                removeRelay(opt.target._removeRelayId);
                return;
            }
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
                movedRelayIds.add(rid);
                const icon = projectorIcons[rid];
                if (icon && icon.label) {
                    icon.label.set({
                        left: opt.target.left,
                        top: opt.target.top + PROJ_RADIUS + 4,
                    });
                    icon.label.setCoords();
                }
                const off = PROJ_RADIUS - 1;
                [icon && icon.trash, icon && icon.trashMark].forEach((o) => {
                    if (!o) return;
                    o.set({ left: opt.target.left + off, top: opt.target.top - off });
                    o.setCoords();
                });
                // L'affectation suit la position : recalcul en direct, la liste des
                // zones montre immédiatement ce que le geste vient de changer.
                recomputeRelayAssignments();
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
            // Redimensionner une zone change ce qu'elle contient : un projecteur peut
            // entrer ou sortir de son périmètre, donc être affecté ou désaffecté.
            if (editingType === 'zone') recomputeRelayAssignments();
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
            skip_keypoint_filter: false,
            debounce_frames: null,
            debounce_reset_seconds: null,
            fabricObj: fabricObj,
        });

        // Réinitialiser l'état de dessin
        currentPoints = [];
        tempLines = [];
        tempCircles = [];
        isDrawing = false;

        // Une zone tracée autour d'un projecteur déjà posé l'adopte aussitôt :
        // l'affectation est géométrique, elle ne dépend pas de l'ordre des gestes.
        recomputeRelayAssignments();
        fabricCanvas.renderAll();
        const adoptes = completedZones[completedZones.length - 1].relays;
        setStatus(`Zone "${name}" créée — ${completedZones.length} zone(s) au total` +
                  (adoptes.length ? ` — projecteurs R${adoptes.join(', R')}` : ' — aucun projecteur dedans'));
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
                // Relais en lecture seule : l'affectation vient de la POSITION des
                // icônes (le centre fait foi). Des cases à cocher ici créeraient une
                // seconde source de vérité, qui divergerait au premier déplacement.
                const relaisAffectes = zone.relays || [];
                const badges = relaisAffectes.length
                    ? relaisAffectes.map((rn) => `<span class="relay-badge" title="Projecteur R${rn} posé dans cette zone">R${rn}</span>`).join('')
                    : '<span class="relay-badge none" title="Aucun projecteur posé dans cette zone : elle ne déclenche aucune alerte physique">aucun</span>';
                const relayCheckboxes = `<div class="zone-relays-derived" onclick="event.stopPropagation()">
                    <span class="zone-relays-label">Projecteurs :</span>${badges}</div>`;
                const skipChecked = zone.skip_keypoint_filter ? 'checked' : '';
                const skipCheckbox = `<div class="zone-skip-kp" onclick="event.stopPropagation()">
                    <label class="skip-kp-label" title="Désactive le filtre anti-chariot sur cette zone. À utiliser uniquement si vous êtes sûr que seuls des piétons y passent.">
                        <input type="checkbox" ${skipChecked} onchange="zoneEditor.toggleSkipKeypointFilter(${i})">
                        <span>🚶 Piétons certains (ignorer filtre pose)</span>
                    </label>
                </div>`;
                const dbFramesVal = zone.debounce_frames != null ? zone.debounce_frames : '';
                const dbResetVal = zone.debounce_reset_seconds != null ? zone.debounce_reset_seconds : '';
                const debounceInputs = `<div class="zone-debounce" onclick="event.stopPropagation()">
                    <span class="zone-debounce-label" title="Nombre de frames positives consécutives avant déclenchement de l'alerte (vide = valeur globale : 2)">⏱ Débounce frames :</span>
                    <input type="number" min="1" max="30" step="1" value="${dbFramesVal}" placeholder="2"
                        class="debounce-input" title="Frames requises avant alerte"
                        onchange="zoneEditor.setDebounceFrames(${i}, this.value)">
                    <span class="zone-debounce-label" title="Secondes sans détection avant remise à zéro du compteur (vide = valeur globale : 0.8)">Reset (s) :</span>
                    <input type="number" min="0.1" max="30" step="0.1" value="${dbResetVal}" placeholder="0.8"
                        class="debounce-input" title="Délai de remise à zéro"
                        onchange="zoneEditor.setDebounceResetSeconds(${i}, this.value)">
                </div>`;
                html += `
                    <div class="zone-item${selected}" data-idx="${i}" onclick="zoneEditor.selectZone(${i})">
                        <div class="zone-item-header">
                            <span class="zone-color-dot" style="background:rgb(${r},${g},${b})"></span>
                            <span class="zone-item-name">${zone.name}</span>
                            <span class="zone-item-points">${pts}pts</span>
                            <button class="zone-item-delete" onclick="event.stopPropagation();zoneEditor.deleteZone(${i})" title="Supprimer">✕</button>
                        </div>
                        ${relayCheckboxes}
                        ${skipCheckbox}
                        ${debounceInputs}
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
            skip_keypoint_filter: zone.skip_keypoint_filter || false,
            debounce_frames: zone.debounce_frames != null ? parseInt(zone.debounce_frames, 10) : null,
            debounce_reset_seconds: zone.debounce_reset_seconds != null ? parseFloat(zone.debounce_reset_seconds) : null,
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
        movedRelayIds.forEach((rid) => {
            const pos = relayPositions[rid];
            if (pos) {
                relayPosData[rid] = {
                    x: Math.round(pos.x * scaleFactor),
                    y: Math.round(pos.y * scaleFactor),
                };
            }
        });
        // `removed` est indispensable : sans lui, un projecteur renvoyé au stock
        // garderait sa position dans relay_positions.ini et redeviendrait affecté à
        // sa zone au prochain chargement.
        const saveRelayPosReq = (movedRelayIds.size > 0 || removedRelayIds.size > 0)
            ? fetch(`/api/relay_positions/${camId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    positions: relayPosData,
                    removed: Array.from(removedRelayIds),
                }),
            }).then((res) => res.json())
            : Promise.resolve({ status: 'ok', count: 0 });

        Promise.all([saveZonesReq, saveMasksReq, saveRelayPosReq])
            .then(([zData, mData]) => {
                showLoading(false);
                const zOk = zData.status === "ok";
                const mOk = mData.status === "ok";
                if (zOk && mOk) {
                    movedRelayIds.clear();
                    removedRelayIds.clear();
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
            skip_keypoint_filter: z.skip_keypoint_filter || false,
            debounce_frames: z.debounce_frames != null ? z.debounce_frames : null,
            debounce_reset_seconds: z.debounce_reset_seconds != null ? z.debounce_reset_seconds : null,
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
                    skip_keypoint_filter: z.skip_keypoint_filter || false,
                    debounce_frames: z.debounce_frames != null ? z.debounce_frames : null,
                    debounce_reset_seconds: z.debounce_reset_seconds != null ? z.debounce_reset_seconds : null,
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
     * Bascule le flag skip_keypoint_filter pour une zone.
     */
    function toggleSkipKeypointFilter(zoneIdx) {
        const zone = completedZones[zoneIdx];
        if (!zone) return;
        zone.skip_keypoint_filter = !zone.skip_keypoint_filter;
        updateZoneList();
    }

    /**
     * Définit le nombre de frames de débounce pour une zone.
     * Valeur vide = utiliser la valeur globale (null dans l'objet).
     */
    function setDebounceFrames(zoneIdx, value) {
        const zone = completedZones[zoneIdx];
        if (!zone) return;
        const v = value.trim();
        zone.debounce_frames = v !== '' ? Math.max(1, parseInt(v, 10)) : null;
    }

    /**
     * Définit le délai de remise à zéro du débounce (en secondes) pour une zone.
     * Valeur vide = utiliser la valeur globale (null dans l'objet).
     */
    function setDebounceResetSeconds(zoneIdx, value) {
        const zone = completedZones[zoneIdx];
        if (!zone) return;
        const v = value.trim();
        zone.debounce_reset_seconds = v !== '' ? Math.max(0.1, parseFloat(v)) : null;
    }

    // === API publique (pour les onclick du HTML) ===
    window.zoneEditor = {
        selectZone: selectZone,
        deleteZone: deleteZone,
        placeRelay: placeRelay,
        removeRelay: removeRelay,
        toggleSkipKeypointFilter: toggleSkipKeypointFilter,
        setDebounceFrames: setDebounceFrames,
        setDebounceResetSeconds: setDebounceResetSeconds,
        selectMask: selectMask,
        deleteMask: deleteMask,
    };

    // Lancer au chargement
    document.addEventListener("DOMContentLoaded", init);
})();
