        /*
         * Everything Capture — frontend graph module.
         * This software is licensed under Elastic License 2.0; see the LICENSE file.
         * Unauthorized use for hosted or managed services is strictly prohibited.
         * For commercial or SaaS licensing, contact:
         * https://github.com/agentenatalie
         */
        // ── Graph View ──────────────────────────────────────────────
        // D3 force-directed graph with Canvas rendering.
        // Edges based on content similarity (TF-IDF cosine).
        // Click node → show connection panel → click to open reader.

        let _graphSim = null;
        let _graphZoom = null;
        let _graphNodes = [];
        let _graphEdges = [];
        let _graphFolderColors = {};
        let _graphHoverNode = null;
        let _graphDragNode = null;
        let _graphSelectedNode = null;
        let _graphTransform = d3.zoomIdentity;
        let _graphAnimFrame = null;
        let _graphNeighborMap = new Map();
        let _graphEdgeByNode = new Map();
        let _graphLoaded = false;
        let _graphFolderFilter = null;
        let _graphInteractionSetup = false;
        let _graphCanvasCtx = null;
        let _graphCachedRadii = new Map();
        let _graphSearchMatches = [];
        let _graphSearchIndex = -1;

        const GRAPH_PALETTE = [
            '#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6',
            '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16',
            '#e879f9', '#22d3ee', '#fb923c', '#a78bfa', '#34d399',
            '#fbbf24', '#f87171', '#2dd4bf', '#c084fc', '#4ade80',
        ];
        const GRAPH_UNFILED_COLOR = '#94a3b8';
        const GRAPH_EDGE_COLOR = 'rgba(120, 120, 160, 1)';

        function _graphBuildFolderColors(folders) {
            _graphFolderColors = {};
            folders.forEach((f, i) => {
                _graphFolderColors[f.id] = GRAPH_PALETTE[i % GRAPH_PALETTE.length];
            });
        }

        function _graphNodeColor(node) {
            if (node.folder_ids && node.folder_ids.length > 0) {
                return _graphFolderColors[node.folder_ids[0]] || GRAPH_UNFILED_COLOR;
            }
            return GRAPH_UNFILED_COLOR;
        }

        function _graphComputeRadii() {
            _graphCachedRadii.clear();
            for (const n of _graphNodes) {
                const edges = _graphEdgeByNode.get(n.id);
                const count = edges ? edges.length : 0;
                _graphCachedRadii.set(n.id, Math.min(4 + Math.sqrt(count) * 2, 13));
            }
        }

        function _graphBuildNeighborMap(nodes, edges) {
            _graphNeighborMap = new Map();
            _graphEdgeByNode = new Map();
            for (const n of nodes) {
                _graphNeighborMap.set(n.id, new Set());
                _graphEdgeByNode.set(n.id, []);
            }
            for (let idx = 0; idx < edges.length; idx++) {
                const e = edges[idx];
                const sid = typeof e.source === 'object' ? e.source.id : e.source;
                const tid = typeof e.target === 'object' ? e.target.id : e.target;
                _graphNeighborMap.get(sid)?.add(tid);
                _graphNeighborMap.get(tid)?.add(sid);
                _graphEdgeByNode.get(sid)?.push(idx);
                _graphEdgeByNode.get(tid)?.push(idx);
            }
        }

        function _graphRequestRedraw() {
            if (_graphAnimFrame) return;
            _graphAnimFrame = requestAnimationFrame(() => {
                _graphAnimFrame = null;
                _graphDraw();
            });
        }

        // ── Get the active highlight set (hover takes priority, then selected) ──
        function _graphActiveSet() {
            const focusNode = _graphHoverNode || _graphSelectedNode;
            if (!focusNode) return null;
            const set = new Set();
            set.add(focusNode.id);
            const neighbors = _graphNeighborMap.get(focusNode.id);
            if (neighbors) for (const nid of neighbors) set.add(nid);
            return { focusNode, set };
        }

        function _graphDraw() {
            const canvas = graphCanvas;
            if (!canvas) return;
            const ctx = _graphCanvasCtx || (_graphCanvasCtx = canvas.getContext('2d'));
            const dpr = window.devicePixelRatio || 1;
            const w = graphContainer.clientWidth;
            const h = graphContainer.clientHeight;

            if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
                canvas.width = w * dpr;
                canvas.height = h * dpr;
                canvas.style.width = w + 'px';
                canvas.style.height = h + 'px';
            }

            ctx.save();
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.scale(dpr, dpr);
            ctx.translate(_graphTransform.x, _graphTransform.y);
            ctx.scale(_graphTransform.k, _graphTransform.k);

            const active = _graphActiveSet();
            const hasActive = active !== null;
            const activeSet = active ? active.set : null;
            const focusNode = active ? active.focusNode : null;
            const hasSearch = _graphSearchMatches.length > 0;
            const searchSet = hasSearch ? new Set(_graphSearchMatches.map(n => n.id)) : null;
            const currentMatchId = hasSearch && _graphSearchIndex >= 0 ? _graphSearchMatches[_graphSearchIndex]?.id : null;

            // Folder highlight set
            const hasFolderHL = _graphHighlightFolderId !== null && !hasActive;
            const highlightedFolderIds = hasFolderHL ? _graphCollectFolderSubtreeIds(_graphHighlightFolderId) : null;
            const folderHLSet = hasFolderHL ? new Set(_graphNodes.filter(n => {
                if (_graphHighlightFolderId === '__unfiled') return !n.folder_ids || n.folder_ids.length === 0;
                return Array.isArray(n.folder_ids) && n.folder_ids.some(folderId => highlightedFolderIds?.has(folderId));
            }).map(n => n.id)) : null;

            const dimForFilter = (hasSearch || hasFolderHL) && !hasActive;

            // ── Edges ──
            if (!hasActive) {
                ctx.globalAlpha = dimForFilter ? 0.03 : 0.08;
                ctx.lineWidth = 0.5;
                ctx.strokeStyle = GRAPH_EDGE_COLOR;
                ctx.beginPath();
                for (const e of _graphEdges) {
                    const s = e.source, t = e.target;
                    if (!s || !t || s.x == null || t.x == null) continue;
                    ctx.moveTo(s.x, s.y);
                    ctx.lineTo(t.x, t.y);
                }
                ctx.stroke();
            } else {
                // Dim edges
                ctx.globalAlpha = 0.03;
                ctx.lineWidth = 0.4;
                ctx.strokeStyle = GRAPH_EDGE_COLOR;
                ctx.beginPath();
                for (const e of _graphEdges) {
                    const s = e.source, t = e.target;
                    if (!s || !t || s.x == null || t.x == null) continue;
                    if (activeSet.has(s.id) && activeSet.has(t.id)) continue;
                    ctx.moveTo(s.x, s.y);
                    ctx.lineTo(t.x, t.y);
                }
                ctx.stroke();
                // Highlighted edges
                ctx.globalAlpha = 0.4;
                ctx.lineWidth = 1.2;
                ctx.strokeStyle = _graphNodeColor(focusNode);
                ctx.beginPath();
                for (const e of _graphEdges) {
                    const s = e.source, t = e.target;
                    if (!s || !t || s.x == null || t.x == null) continue;
                    if (!(activeSet.has(s.id) && activeSet.has(t.id))) continue;
                    ctx.moveTo(s.x, s.y);
                    ctx.lineTo(t.x, t.y);
                }
                ctx.stroke();
            }

            // ── Nodes ──
            ctx.lineWidth = 0.8;
            ctx.strokeStyle = 'rgba(255,255,255,0.5)';

            if (!hasActive) {
                for (const n of _graphNodes) {
                    if (n.x == null) continue;
                    const inSearch = searchSet && searchSet.has(n.id);
                    const inFolder = folderHLSet && folderHLSet.has(n.id);
                    ctx.globalAlpha = dimForFilter ? ((inSearch || inFolder) ? 1 : 0.1) : 1;
                    const r = _graphCachedRadii.get(n.id) || 5;
                    ctx.fillStyle = _graphNodeColor(n);
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, r, 0, 6.2832);
                    ctx.fill();
                    ctx.stroke();
                }
            } else {
                for (const n of _graphNodes) {
                    if (n.x == null) continue;
                    const inActive = activeSet.has(n.id);
                    ctx.globalAlpha = inActive ? 1 : 0.1;
                    const r = _graphCachedRadii.get(n.id) || 5;
                    ctx.fillStyle = _graphNodeColor(n);
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, r, 0, 6.2832);
                    ctx.fill();
                    ctx.stroke();
                }
                // Ring on focus node
                if (focusNode && focusNode.x != null) {
                    const r = (_graphCachedRadii.get(focusNode.id) || 5) + 3;
                    ctx.globalAlpha = 0.4;
                    ctx.strokeStyle = _graphNodeColor(focusNode);
                    ctx.lineWidth = 2;
                    ctx.beginPath();
                    ctx.arc(focusNode.x, focusNode.y, r, 0, 6.2832);
                    ctx.stroke();
                }
            }

            // ── Search match rings ──
            if (hasSearch) {
                ctx.lineWidth = 2.5;
                ctx.strokeStyle = '#999';
                for (const n of _graphSearchMatches) {
                    if (n.x == null) continue;
                    const r = (_graphCachedRadii.get(n.id) || 5) + 4;
                    ctx.globalAlpha = 0.7;
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, r, 0, 6.2832);
                    ctx.stroke();
                }
                // Brighter ring + glow on current match
                if (currentMatchId) {
                    const cn = _graphSearchMatches[_graphSearchIndex];
                    if (cn && cn.x != null) {
                        const r = (_graphCachedRadii.get(cn.id) || 5) + 5;
                        ctx.globalAlpha = 0.25;
                        ctx.strokeStyle = '#999';
                        ctx.lineWidth = 8;
                        ctx.beginPath();
                        ctx.arc(cn.x, cn.y, r + 3, 0, 6.2832);
                        ctx.stroke();
                        ctx.globalAlpha = 1;
                        ctx.lineWidth = 3;
                        ctx.beginPath();
                        ctx.arc(cn.x, cn.y, r, 0, 6.2832);
                        ctx.stroke();
                    }
                }
            }

            // ── Labels ──
            const zoom = _graphTransform.k;
            const fontSize = Math.max(9, Math.min(13, 11 / zoom));
            ctx.font = `${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';

            const minRadiusForLabel = Math.max(0, 12 - zoom * 8);

            for (const n of _graphNodes) {
                if (n.x == null) continue;
                const r = _graphCachedRadii.get(n.id) || 5;
                const title = n.title || '';
                if (!title) continue;

                let showLabel = false;
                let labelAlpha = 0.75;

                if (hasActive) {
                    if (activeSet.has(n.id)) {
                        showLabel = true;
                        labelAlpha = n === focusNode ? 1 : 0.85;
                    } else if (r >= minRadiusForLabel && zoom >= 0.5) {
                        showLabel = true;
                        labelAlpha = 0.08;
                    }
                } else if (dimForFilter) {
                    const inHL = (searchSet && searchSet.has(n.id)) || (folderHLSet && folderHLSet.has(n.id));
                    if (inHL) {
                        showLabel = true;
                        labelAlpha = (searchSet && n.id === currentMatchId) ? 1 : 0.85;
                    } else if (r >= minRadiusForLabel && zoom >= 0.5) {
                        showLabel = true;
                        labelAlpha = 0.08;
                    }
                } else {
                    showLabel = r >= minRadiusForLabel;
                    labelAlpha = Math.min(0.8, 0.3 + (r - minRadiusForLabel) * 0.12);
                }

                if (!showLabel) continue;

                const label = title.length > 20 ? title.slice(0, 19) + '…' : title;
                ctx.globalAlpha = labelAlpha;
                ctx.fillStyle = 'rgba(50, 50, 50, 0.9)';
                ctx.fillText(label, n.x, n.y + r + 3);
            }

            ctx.restore();
        }

        function _graphHitTest(mx, my) {
            const x = _graphTransform.invertX(mx);
            const y = _graphTransform.invertY(my);
            let closest = null;
            let closestDist = Infinity;
            for (const n of _graphNodes) {
                if (n.x == null) continue;
                const r = (_graphCachedRadii.get(n.id) || 5) + 4;
                const dx = n.x - x;
                const dy = n.y - y;
                const dist = dx * dx + dy * dy;
                if (dist < r * r && dist < closestDist) {
                    closestDist = dist;
                    closest = n;
                }
            }
            return closest;
        }

        // ── Node panel ──
        function _graphShowNodePanel(node, screenX, screenY) {
            const panel = document.getElementById('graphNodePanel');
            if (!panel) return;

            // Get connected nodes with scores
            const connections = [];
            const edgeIndices = _graphEdgeByNode.get(node.id) || [];
            for (const idx of edgeIndices) {
                const e = _graphEdges[idx];
                if (!e) continue;
                const s = typeof e.source === 'object' ? e.source : null;
                const t = typeof e.target === 'object' ? e.target : null;
                if (!s || !t) continue;
                const other = s.id === node.id ? t : s;
                connections.push({ node: other, score: e.score || 0 });
            }
            connections.sort((a, b) => b.score - a.score);

            const folders = (node.folder_names || []).join(', ') || '未分类';
            let html = `
                <div class="graph-node-panel-header" data-node-id="${node.id}">
                    <div class="graph-node-panel-title">${escapeHtml(node.title || '无标题')}</div>
                    <div class="graph-node-panel-meta">${escapeHtml(folders)} · ${escapeHtml(node.platform || '')}</div>
                </div>`;

            if (connections.length > 0) {
                html += `<div class="graph-node-panel-section-label">相关内容 (${connections.length})</div>`;
                html += '<div class="graph-node-panel-section">';
                for (const c of connections) {
                    const color = _graphNodeColor(c.node);
                    const pct = Math.round(c.score * 100);
                    html += `<div class="graph-node-panel-item" data-node-id="${c.node.id}">
                        <span class="graph-node-panel-dot" style="background:${color}"></span>
                        <span class="graph-node-panel-item-title">${escapeHtml(c.node.title || '无标题')}</span>
                        <span class="graph-node-panel-score">${pct}%</span>
                    </div>`;
                }
                html += '</div>';
            } else {
                html += '<div class="graph-node-panel-section-label" style="padding:12px 14px;color:#bbb;">暂无相关内容</div>';
            }

            panel.innerHTML = html;

            // Position: try right of cursor, flip if overflow
            const cRect = graphContainer.getBoundingClientRect();
            let left = screenX + 16;
            let top = screenY - 20;
            if (left + 290 > cRect.width) left = screenX - 296;
            if (top + 360 > cRect.height) top = cRect.height - 370;
            if (top < 10) top = 10;
            panel.style.left = left + 'px';
            panel.style.top = top + 'px';

            // Show
            requestAnimationFrame(() => panel.classList.add('visible'));

            // Click handlers
            panel.querySelectorAll('[data-node-id]').forEach(el => {
                el.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const nid = el.dataset.nodeId;
                    const isHeader = el.classList.contains('graph-node-panel-header');
                    if (isHeader) {
                        // Click header → open reader
                        _graphOpenItem(nid);
                    } else {
                        // Click connection → focus that node and show its panel
                        const targetNode = _graphNodes.find(n => n.id === nid);
                        if (targetNode) {
                            _graphSelectNode(targetNode, screenX, screenY);
                        }
                    }
                });
            });
        }

        function _graphHideNodePanel() {
            const panel = document.getElementById('graphNodePanel');
            if (panel) panel.classList.remove('visible');
        }

        function _graphSelectNode(node, screenX, screenY) {
            _graphSelectedNode = node;
            _graphRequestRedraw();
            // Compute screen position from node coords
            if (node.x != null && (screenX === undefined || screenY === undefined)) {
                screenX = _graphTransform.applyX(node.x);
                screenY = _graphTransform.applyY(node.y);
            }
            _graphShowNodePanel(node, screenX, screenY);
        }

        function _graphDeselectNode() {
            _graphSelectedNode = null;
            _graphHideNodePanel();
            _graphRequestRedraw();
        }

        function _graphOpenItem(nodeId) {
            _graphHideNodePanel();
            // Use handleItemPrimaryAction which does pushState to /reader/{id}
            if (typeof handleItemPrimaryAction === 'function') {
                handleItemPrimaryAction(nodeId);
            }
        }

        function _graphSetupInteraction() {
            if (_graphInteractionSetup) return;
            _graphInteractionSetup = true;
            const canvas = graphCanvas;

            _graphZoom = d3.zoom()
                .scaleExtent([0.08, 8])
                .on('zoom', (event) => {
                    _graphTransform = event.transform;
                    _graphRequestRedraw();
                    // Hide panel on zoom/pan
                    if (_graphSelectedNode) _graphDeselectNode();
                })
                .filter((event) => {
                    // Let our custom wheel handler deal with wheel events
                    if (event.type === 'wheel') return false;
                    return !event.ctrlKey && !event.button;
                });

            d3.select(canvas).call(_graphZoom)
                .on('dblclick.zoom', null);

            // Custom trackpad: vertical = zoom, horizontal = pan
            canvas.addEventListener('wheel', (e) => {
                e.preventDefault();
                const absX = Math.abs(e.deltaX);
                const absY = Math.abs(e.deltaY);

                if (e.ctrlKey || (absY > absX * 1.2)) {
                    // Vertical dominant or pinch → zoom
                    const scaleBy = e.ctrlKey
                        ? Math.pow(2, -e.deltaY * 0.01)
                        : Math.pow(2, -e.deltaY * 0.005);
                    const rect = canvas.getBoundingClientRect();
                    const mx = e.clientX - rect.left;
                    const my = e.clientY - rect.top;
                    const newK = Math.min(8, Math.max(0.08, _graphTransform.k * scaleBy));
                    const newX = mx - (mx - _graphTransform.x) * (newK / _graphTransform.k);
                    const newY = my - (my - _graphTransform.y) * (newK / _graphTransform.k);
                    _graphTransform = d3.zoomIdentity.translate(newX, newY).scale(newK);
                } else {
                    // Horizontal dominant → pan
                    _graphTransform = d3.zoomIdentity
                        .translate(_graphTransform.x - e.deltaX, _graphTransform.y - e.deltaY)
                        .scale(_graphTransform.k);
                }

                // Sync d3 zoom state
                d3.select(canvas).call(_graphZoom.transform, _graphTransform);
            }, { passive: false });

            // Hover
            canvas.addEventListener('mousemove', (e) => {
                const rect = canvas.getBoundingClientRect();
                const mx = e.clientX - rect.left;
                const my = e.clientY - rect.top;
                const node = _graphHitTest(mx, my);

                if (node !== _graphHoverNode) {
                    _graphHoverNode = node;
                    canvas.style.cursor = node ? 'pointer' : 'grab';
                    _graphRequestRedraw();
                }

                if (node) {
                    let tip = node.title || '无标题';
                    if (node.folder_names && node.folder_names.length) {
                        tip += ' · ' + node.folder_names.join(', ');
                    }
                    graphTooltip.textContent = tip;
                    graphTooltip.style.left = (mx + 14) + 'px';
                    graphTooltip.style.top = (my - 8) + 'px';
                    graphTooltip.classList.add('visible');
                } else {
                    graphTooltip.classList.remove('visible');
                }
            });

            canvas.addEventListener('mouseleave', () => {
                if (_graphHoverNode) {
                    _graphHoverNode = null;
                    graphTooltip.classList.remove('visible');
                    _graphRequestRedraw();
                }
            });

            // Click — show panel (not open reader directly)
            canvas.addEventListener('click', (e) => {
                if (_graphDragNode) return;
                const rect = canvas.getBoundingClientRect();
                const mx = e.clientX - rect.left;
                const my = e.clientY - rect.top;
                const node = _graphHitTest(mx, my);

                if (node) {
                    _graphSelectNode(node, mx, my);
                } else {
                    // Click empty area → deselect
                    if (_graphSelectedNode) _graphDeselectNode();
                    if (_graphHighlightFolderId) _graphClearFolderHighlight();
                }
            });

            // Drag
            let dragStartX, dragStartY, dragMoved;
            canvas.addEventListener('mousedown', (e) => {
                const rect = canvas.getBoundingClientRect();
                const node = _graphHitTest(e.clientX - rect.left, e.clientY - rect.top);
                if (!node) return;

                dragMoved = false;
                dragStartX = e.clientX;
                dragStartY = e.clientY;
                _graphDragNode = node;
                node.fx = node.x;
                node.fy = node.y;
                _graphSim.alphaTarget(0.3).restart();
                d3.select(canvas).on('.zoom', null);

                const onMove = (ev) => {
                    if (Math.abs(ev.clientX - dragStartX) + Math.abs(ev.clientY - dragStartY) > 3) dragMoved = true;
                    node.fx = _graphTransform.invertX(ev.clientX - rect.left);
                    node.fy = _graphTransform.invertY(ev.clientY - rect.top);
                };
                const onUp = () => {
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                    node.fx = null;
                    node.fy = null;
                    _graphDragNode = null;
                    _graphSim.alphaTarget(0);
                    d3.select(canvas).call(_graphZoom);
                };
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
                e.preventDefault();
                e.stopPropagation();
            });
        }

        let _graphFoldersData = [];
        let _graphHighlightFolderId = null;

        function _graphCollectFolderSubtreeIds(folderId) {
            const targetId = String(folderId || '').trim();
            if (!targetId || targetId === '__unfiled') return new Set();

            const sourceFolders = (typeof foldersData !== 'undefined' && Array.isArray(foldersData) && foldersData.length)
                ? foldersData
                : _graphFoldersData;
            const childrenByParent = new Map();

            for (const folder of sourceFolders || []) {
                const id = String(folder?.id || '').trim();
                if (!id) continue;
                const parentId = folder?.parent_id ? String(folder.parent_id).trim() : '';
                if (!childrenByParent.has(parentId)) {
                    childrenByParent.set(parentId, []);
                }
                childrenByParent.get(parentId).push(id);
            }

            const subtreeIds = new Set();
            const queue = [targetId];
            while (queue.length) {
                const currentId = queue.shift();
                if (!currentId || subtreeIds.has(currentId)) continue;
                subtreeIds.add(currentId);
                const childIds = childrenByParent.get(currentId) || [];
                childIds.forEach((childId) => {
                    if (!subtreeIds.has(childId)) {
                        queue.push(childId);
                    }
                });
            }

            return subtreeIds;
        }

        function _graphRenderLegend(folders) {
            _graphFoldersData = folders;
            const legend = document.getElementById('graphLegend');
            if (!legend) return;
            let html = '';
            for (const f of folders) {
                const color = _graphFolderColors[f.id] || GRAPH_UNFILED_COLOR;
                html += `<span class="graph-legend-item" data-folder-id="${f.id}"><span class="graph-legend-dot" style="background:${color}"></span>${escapeHtml(f.name)}</span>`;
            }
            html += `<span class="graph-legend-item" data-folder-id="__unfiled"><span class="graph-legend-dot" style="background:${GRAPH_UNFILED_COLOR}"></span>未分类</span>`;
            legend.innerHTML = html;

            legend.querySelectorAll('.graph-legend-item').forEach(el => {
                el.addEventListener('click', () => {
                    const fid = el.dataset.folderId;
                    if (_graphHighlightFolderId === fid) {
                        _graphClearFolderHighlight();
                    } else {
                        _graphHighlightFolder(fid);
                    }
                });
            });
        }

        function _graphHighlightFolder(folderId) {
            _graphHighlightFolderId = folderId;
            document.querySelectorAll('.graph-legend-item.expanded').forEach(el => el.classList.remove('expanded'));
            const el = document.querySelector(`.graph-legend-item[data-folder-id="${folderId}"]`);
            if (el) el.classList.add('expanded');
            _graphRequestRedraw();
        }

        function _graphClearFolderHighlight() {
            _graphHighlightFolderId = null;
            document.querySelectorAll('.graph-legend-item.expanded').forEach(el => el.classList.remove('expanded'));
            _graphRequestRedraw();
        }

        function _graphFitView() {
            if (!_graphNodes.length || !_graphZoom) return;
            const w = graphContainer.clientWidth;
            const h = graphContainer.clientHeight;

            let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
            for (const n of _graphNodes) {
                if (n.x == null) continue;
                minX = Math.min(minX, n.x);
                maxX = Math.max(maxX, n.x);
                minY = Math.min(minY, n.y);
                maxY = Math.max(maxY, n.y);
            }
            if (minX === Infinity) return;

            const padding = 80;
            const graphW = (maxX - minX) || 1;
            const graphH = (maxY - minY) || 1;
            const scale = Math.min((w - padding * 2) / graphW, (h - padding * 2) / graphH, 2.5);

            const transform = d3.zoomIdentity
                .translate(w / 2, h / 2)
                .scale(scale)
                .translate(-(minX + maxX) / 2, -(minY + maxY) / 2);

            d3.select(graphCanvas)
                .transition().duration(600).ease(d3.easeCubicInOut)
                .call(_graphZoom.transform, transform);
        }

        async function initGraph() {
            const folderId = (typeof currentFolderId !== 'undefined' && currentFolderScope === 'folder')
                ? currentFolderId : null;

            if (_graphLoaded && _graphFolderFilter === folderId) {
                graphContainer.style.display = 'block';
                _graphRequestRedraw();
                return;
            }
            _graphFolderFilter = folderId;

            try {
                let url = (window.API_BASE_URL || '') + '/api/items/graph';
                if (folderId) url += '?folder_id=' + encodeURIComponent(folderId);
                const res = await fetch(url);
                if (!res.ok) throw new Error('Graph API failed');
                const data = await res.json();

                _graphBuildFolderColors(data.folders);
                _graphNodes = data.nodes.map(n => ({ ...n }));
                _graphEdges = data.edges.map(e => ({ ...e }));
                _graphBuildNeighborMap(_graphNodes, _graphEdges);
                _graphComputeRadii();
                _graphRenderLegend(data.folders);

                for (const n of _graphNodes) {
                    if (!extraItemCache.has(n.id)) {
                        extraItemCache.set(n.id, {
                            id: n.id, title: n.title, platform: n.platform,
                            source_url: '',
                            media: n.media_url ? [{ type: 'image', url: n.media_url, original_url: '', display_order: 0 }] : [],
                            folder_ids: n.folder_ids || [], folder_names: n.folder_names || [],
                        });
                    }
                }

                if (_graphSim) _graphSim.stop();

                const cx = graphContainer.clientWidth / 2;
                const cy = graphContainer.clientHeight / 2;

                _graphSim = d3.forceSimulation(_graphNodes)
                    .force('charge', d3.forceManyBody().strength(-80).distanceMax(350))
                    .force('link', d3.forceLink(_graphEdges).id(d => d.id).distance(60).strength(0.25))
                    .force('center', d3.forceCenter(cx, cy))
                    .force('collision', d3.forceCollide().radius(d => (_graphCachedRadii.get(d.id) || 5) + 2).strength(0.5))
                    .force('x', d3.forceX(cx).strength(0.015))
                    .force('y', d3.forceY(cy).strength(0.015))
                    .alphaDecay(0.025)
                    .velocityDecay(0.4)
                    .on('tick', _graphRequestRedraw);

                _graphTransform = d3.zoomIdentity;
                _graphSetupInteraction();
                _graphLoaded = true;
                _graphSelectedNode = null;
                _graphHideNodePanel();

                setTimeout(() => _graphFitView(), 1000);
            } catch (err) {
                console.error('Graph load error:', err);
            }
        }

        // ── Graph Search ──
        function _graphSearchExec(query) {
            const countEl = document.getElementById('graphSearchCount');
            const resultsEl = document.getElementById('graphSearchResults');

            query = (query || '').trim().toLowerCase();
            if (!query) {
                _graphSearchMatches = [];
                _graphSearchIndex = -1;
                countEl.textContent = '';
                resultsEl.innerHTML = '';
                resultsEl.classList.remove('visible');
                _graphRequestRedraw();
                return;
            }

            // Expand query using AI memories (e.g. "我的项目" → "我的项目 Everything Capture")
            const expanded = expandQueryWithMemories(query).toLowerCase();
            const originalTerms = query.toLowerCase().split(/\s+/).filter(Boolean);
            const expandedTerms = expanded.split(/\s+/).filter(Boolean);
            // Extra terms added by memory expansion (OR matching)
            const extraTerms = expandedTerms.filter(t => !originalTerms.includes(t));

            _graphSearchMatches = _graphNodes.filter(n => {
                const text = ((n.title || '') + ' ' + (n.folder_names || []).join(' ') + ' ' + (n.platform || '')).toLowerCase();
                // Original terms: all must match (AND)
                const originalMatch = originalTerms.every(t => text.includes(t));
                // Memory-expanded terms: any match (OR)
                const memoryMatch = extraTerms.length > 0 && extraTerms.some(t => text.includes(t));
                return originalMatch || memoryMatch;
            });

            if (_graphSearchMatches.length > 0) {
                _graphSearchIndex = 0;
                countEl.textContent = `${_graphSearchMatches.length} 个结果`;
                _graphZoomToNode(_graphSearchMatches[0]);
            } else {
                _graphSearchIndex = -1;
                countEl.textContent = '无结果';
            }
            _graphRenderSearchResults();
            _graphRequestRedraw();
        }

        function _graphRenderSearchResults() {
            const resultsEl = document.getElementById('graphSearchResults');
            if (!resultsEl) return;

            if (_graphSearchMatches.length === 0) {
                resultsEl.innerHTML = '';
                resultsEl.classList.remove('visible');
                return;
            }

            let html = '';
            for (let i = 0; i < _graphSearchMatches.length; i++) {
                const n = _graphSearchMatches[i];
                const color = _graphNodeColor(n);
                const folders = (n.folder_names || []).join(', ') || '未分类';
                const active = i === _graphSearchIndex ? ' active' : '';
                html += `<div class="graph-search-result-item${active}" data-search-idx="${i}">
                    <span class="graph-search-result-dot" style="background:${color}"></span>
                    <div class="graph-search-result-info">
                        <div class="graph-search-result-title">${escapeHtml(n.title || '无标题')}</div>
                        <div class="graph-search-result-meta">${escapeHtml(folders)} · ${escapeHtml(n.platform || '')}</div>
                    </div>
                </div>`;
            }
            resultsEl.innerHTML = html;
            resultsEl.classList.add('visible');

            resultsEl.querySelectorAll('.graph-search-result-item').forEach(el => {
                el.addEventListener('click', () => {
                    const idx = parseInt(el.dataset.searchIdx, 10);
                    _graphSearchIndex = idx;
                    const countEl = document.getElementById('graphSearchCount');
                    countEl.textContent = `${_graphSearchMatches.length} 个结果`;
                    _graphZoomToNode(_graphSearchMatches[idx]);
                    _graphRenderSearchResults();
                    _graphRequestRedraw();
                });
            });

            // Scroll active item into view
            const activeEl = resultsEl.querySelector('.graph-search-result-item.active');
            if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
        }

        function _graphSearchNavigate(delta) {
            if (_graphSearchMatches.length === 0) return;
            _graphSearchIndex = (_graphSearchIndex + delta + _graphSearchMatches.length) % _graphSearchMatches.length;
            const countEl = document.getElementById('graphSearchCount');
            countEl.textContent = `${_graphSearchMatches.length} 个结果`;
            _graphZoomToNode(_graphSearchMatches[_graphSearchIndex]);
            _graphRenderSearchResults();
            _graphRequestRedraw();
        }

        function _graphZoomToNode(node) {
            if (!node || node.x == null || !_graphZoom) return;
            const w = graphContainer.clientWidth;
            const h = graphContainer.clientHeight;
            const scale = Math.max(_graphTransform.k, 1.8);
            const transform = d3.zoomIdentity
                .translate(w / 2, h / 2)
                .scale(scale)
                .translate(-node.x, -node.y);

            d3.select(graphCanvas)
                .transition().duration(500).ease(d3.easeCubicInOut)
                .call(_graphZoom.transform, transform);
        }

        // Wire up search UI
        (function _graphSearchInit() {
            let debounceTimer = null;
            const input = document.getElementById('graphSearchInput');
            if (!input) return;

            input.addEventListener('input', () => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => _graphSearchExec(input.value), 200);
            });

            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    _graphSearchNavigate(e.shiftKey ? -1 : 1);
                } else if (e.key === 'Escape') {
                    input.value = '';
                    _graphSearchExec('');
                    input.blur();
                }
            });

            // Cmd+S to focus search bar in graph view
            document.addEventListener('keydown', (e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === 's' && currentView === 'graph') {
                    e.preventDefault();
                    input.focus();
                    input.select();
                }
            });
        })();

        function destroyGraph() {
            if (_graphAnimFrame) { cancelAnimationFrame(_graphAnimFrame); _graphAnimFrame = null; }
            if (_graphSim) _graphSim.stop();
            _graphHoverNode = null;
            _graphSelectedNode = null;
            _graphSearchMatches = [];
            _graphSearchIndex = -1;
            _graphHighlightFolderId = null;
            _graphHideNodePanel();
            graphTooltip.classList.remove('visible');
        }

        let _graphResizeTimer = null;
        window.addEventListener('resize', () => {
            if (currentView !== 'graph') return;
            clearTimeout(_graphResizeTimer);
            _graphResizeTimer = setTimeout(() => {
                if (_graphSim) {
                    const cx = graphContainer.clientWidth / 2;
                    const cy = graphContainer.clientHeight / 2;
                    _graphSim.force('center', d3.forceCenter(cx, cy));
                    _graphSim.force('x', d3.forceX(cx).strength(0.015));
                    _graphSim.force('y', d3.forceY(cy).strength(0.015));
                    _graphSim.alpha(0.2).restart();
                }
            }, 200);
        });
