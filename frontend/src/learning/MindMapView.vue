<script setup>
import { computed, nextTick, onMounted, ref, useTemplateRef, watch } from 'vue'
import LearnIcon from './LearnIcon.vue'
import { formatTs, parseTs } from './learnApi.js'
import { triggerDownload } from '../api.js'

const props = defineProps({
  markdown: { type: String, default: '' },
  title: { type: String, default: '思维导图' },
})
const emit = defineEmits(['seek', 'notify'])

const wrapEl = useTemplateRef('canvas-wrap')
const svgEl = useTemplateRef('mindmap-svg')

const scale = ref(1)
const panX = ref(36)
const panY = ref(36)
const dragging = ref(false)
const showSource = ref(false)
const collapsed = ref(new Set())

let dragStart = { x: 0, y: 0, px: 0, py: 0 }

const PALETTE = [
  { stroke: '#2563eb', fill: '#eff6ff', text: '#1e3a8a', badge: '#dbeafe' },
  { stroke: '#7c3aed', fill: '#f5f3ff', text: '#4c1d95', badge: '#ede9fe' },
  { stroke: '#059669', fill: '#ecfdf5', text: '#065f46', badge: '#d1fae5' },
  { stroke: '#d97706', fill: '#fffbeb', text: '#78350f', badge: '#fef3c7' },
  { stroke: '#db2777', fill: '#fdf2f8', text: '#831843', badge: '#fce7f3' },
  { stroke: '#0891b2', fill: '#ecfeff', text: '#164e63', badge: '#cffafe' },
]

function extractNodeLabel(raw) {
  let text = String(raw || '').replace(/\*\*/g, '').replace(/`/g, '').trim()
  let seekSec = null
  let tsLabel = ''
  const m = text.match(/\[(\d{1,2}:\d{2}(?::\d{2})?)\]/)
  if (m) {
    const parsed = parseTs(m[1])
    if (parsed !== null) {
      seekSec = parsed
      tsLabel = formatTs(parsed)
      text = text.replace(m[0], '').trim()
    }
  }
  text = text.replace(/^[-–—:：\s]+|[-–—:：\s]+$/g, '').trim()
  return { text: text || '要点', seekSec, tsLabel }
}

function wrapLines(text, maxUnits = 30) {
  const lines = []
  let cur = ''
  let units = 0
  for (const ch of text) {
    const w = ch.charCodeAt(0) > 255 ? 2 : 1.1
    if (units + w > maxUnits && cur) {
      lines.push(cur)
      cur = ch
      units = w
      if (lines.length >= 2) break
    } else {
      cur += ch
      units += w
    }
  }
  if (cur && lines.length < 3) {
    lines.push(lines.length === 2 && cur.length > 14 ? `${cur.slice(0, 13)}…` : cur)
  }
  return lines.length ? lines : [text]
}

function measureLinePx(line, fontSize) {
  let px = 0
  for (const ch of line) {
    px += ch.charCodeAt(0) > 255 ? fontSize * 1.02 : fontSize * 0.58
  }
  return px
}

function parseTree(md) {
  const lines = String(md || '').split(/\r?\n/)
  const rootTitle = props.title || '视频核心知识'
  let root = null
  const headingStack = []
  let lastHeadingDepth = 0
  let seq = 0

  const makeNode = (raw, depth) => {
    const { text, seekSec, tsLabel } = extractNodeLabel(raw)
    return { id: `n_${seq++}`, text, seekSec, tsLabel, depth, children: [] }
  }

  for (const rawLine of lines) {
    if (!rawLine.trim() || rawLine.trim().startsWith('```')) continue
    const hMatch = rawLine.match(/^(#{1,4})\s+(.*)$/)
    if (hMatch) {
      const level = hMatch[1].length - 1
      const node = makeNode(hMatch[2], level)
      if (level === 0 && !root) {
        root = node
        headingStack.length = 0
        headingStack[0] = root
        lastHeadingDepth = 0
        continue
      }
      if (!root) {
        root = makeNode(rootTitle, 0)
        headingStack[0] = root
      }
      const targetDepth = Math.max(1, level)
      node.depth = targetDepth
      let parent = root
      for (let d = targetDepth - 1; d >= 0; d--) {
        if (headingStack[d]) {
          parent = headingStack[d]
          break
        }
      }
      parent.children.push(node)
      headingStack[targetDepth] = node
      headingStack.length = targetDepth + 1
      lastHeadingDepth = targetDepth
      continue
    }

    const liMatch = rawLine.match(/^(\s*)(?:[-*•]|\d+[.、)])\s+(.*)$/)
    if (liMatch) {
      if (!root) {
        root = makeNode(rootTitle, 0)
        headingStack[0] = root
      }
      const indentLevel = Math.floor(liMatch[1].replace(/\t/g, '  ').length / 2)
      const depth = lastHeadingDepth + 1 + indentLevel
      const node = makeNode(liMatch[2], depth)
      let parent = headingStack[depth - 1] || headingStack[lastHeadingDepth] || root
      parent.children.push(node)
      headingStack[depth] = node
      headingStack.length = depth + 1
    }
  }

  return root || makeNode(rootTitle, 0)
}

const tree = computed(() => parseTree(props.markdown))

const layout = computed(() => {
  const root = tree.value
  const nodes = []
  const edges = []
  const H_GAP = 64
  const V_GAP = 14
  const PAD = 32

  function prepare(node, depth, branchIdx) {
    const fontSize = depth === 0 ? 15 : depth === 1 ? 13.5 : 12.5
    const lines = wrapLines(node.text, depth === 0 ? 26 : 30)
    const maxTextW = Math.max(...lines.map((l) => measureLinePx(l, fontSize)), 48)
    const tsWidth = node.tsLabel ? measureLinePx(node.tsLabel, 11) + 28 : 0
    const toggleWidth = node.children.length && depth > 0 ? 20 : 0
    const boxW = Math.ceil(maxTextW + tsWidth + toggleWidth + (depth === 0 ? 36 : 28))
    const lineH = fontSize + 6
    const boxH = Math.max(depth === 0 ? 44 : 36, lines.length * lineH + 16)
    const isCollapsed = depth > 0 && collapsed.value.has(node.id)
    const visibleChildren = isCollapsed ? [] : node.children.map((ch, idx) => prepare(ch, depth + 1, depth === 0 ? idx : branchIdx))
    const childrenSpan = visibleChildren.length
      ? visibleChildren.reduce((acc, c) => acc + c.spanH, 0) + V_GAP * (visibleChildren.length - 1)
      : 0
    const spanH = Math.max(boxH, childrenSpan)
    return {
      ...node,
      depth,
      branchIdx,
      fontSize,
      lineH,
      lines,
      boxW,
      boxH,
      isCollapsed,
      hasChildren: node.children.length > 0,
      visibleChildren,
      spanH,
    }
  }

  const prepared = prepare(root, 0, 0)

  function place(item, x, topY) {
    const centerY = topY + item.spanH / 2
    const boxY = centerY - item.boxH / 2
    const color = item.depth === 0
      ? { stroke: '#4f46e5', fill: '#4f46e5', text: '#ffffff', badge: '#6366f1' }
      : PALETTE[item.branchIdx % PALETTE.length]
    const placed = { ...item, x, y: boxY, centerY, color }
    nodes.push(placed)

    if (item.visibleChildren.length) {
      const childX = x + item.boxW + H_GAP
      const totalChildH = item.visibleChildren.reduce((s, c) => s + c.spanH, 0) + V_GAP * (item.visibleChildren.length - 1)
      let cursorY = centerY - totalChildH / 2
      for (const ch of item.visibleChildren) {
        const childPlaced = place(ch, childX, cursorY)
        const sx = x + item.boxW
        const sy = centerY
        const tx = childX
        const ty = childPlaced.centerY
        const mx = sx + (tx - sx) * 0.5
        edges.push({
          id: `${item.id}_${ch.id}`,
          d: `M ${sx} ${sy} C ${mx} ${sy}, ${mx} ${ty}, ${tx} ${ty}`,
          stroke: childPlaced.color.stroke,
        })
        cursorY += ch.spanH + V_GAP
      }
    }
    return placed
  }

  place(prepared, PAD, PAD)
  const maxX = Math.max(...nodes.map((n) => n.x + n.boxW), 320) + PAD
  const maxY = Math.max(...nodes.map((n) => n.y + n.boxH), 200) + PAD
  return { nodes, edges, width: maxX, height: maxY }
})

function fitView() {
  const el = wrapEl.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const sx = (rect.width - 32) / layout.value.width
  const sy = (rect.height - 32) / layout.value.height
  const nextScale = Math.min(1.15, Math.max(0.45, Math.min(sx, sy)))
  scale.value = Number(nextScale.toFixed(2))
  panX.value = Math.round((rect.width - layout.value.width * scale.value) / 2)
  panY.value = Math.max(16, Math.round((rect.height - layout.value.height * scale.value) / 2))
}

function zoomBy(delta) {
  scale.value = Number(Math.min(2.2, Math.max(0.35, scale.value + delta)).toFixed(2))
}

function toggleNode(node) {
  if (!node.hasChildren || node.depth === 0) return
  const next = new Set(collapsed.value)
  if (next.has(node.id)) next.delete(node.id)
  else next.add(node.id)
  collapsed.value = next
}

function expandAll() {
  collapsed.value = new Set()
  nextTick(fitView)
}

function collapseBranches() {
  const next = new Set()
  const walk = (n, d) => {
    if (d >= 1 && n.children?.length) next.add(n.id)
    for (const c of n.children || []) walk(c, d + 1)
  }
  walk(tree.value, 0)
  collapsed.value = next
  nextTick(fitView)
}

function onPointerDown(e) {
  if (e.target.closest('[data-node-action]')) return
  dragging.value = true
  dragStart = { x: e.clientX, y: e.clientY, px: panX.value, py: panY.value }
  e.currentTarget.setPointerCapture?.(e.pointerId)
}

function onPointerMove(e) {
  if (!dragging.value) return
  panX.value = dragStart.px + (e.clientX - dragStart.x)
  panY.value = dragStart.py + (e.clientY - dragStart.y)
}

function onPointerUp() {
  dragging.value = false
}

function onWheel(e) {
  e.preventDefault()
  zoomBy(e.deltaY < 0 ? 0.1 : -0.1)
}

function buildStandaloneSvgString() {
  const { width, height } = layout.value
  const clone = svgEl.value.cloneNode(true)
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))
  clone.setAttribute('viewBox', `0 0 ${width} ${height}`)
  const innerGroup = clone.querySelector('[data-viewport]')
  if (innerGroup) innerGroup.setAttribute('transform', 'translate(0, 0) scale(1)')
  const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
  bg.setAttribute('width', String(width))
  bg.setAttribute('height', String(height))
  bg.setAttribute('fill', '#ffffff')
  clone.insertBefore(bg, clone.firstChild)
  return new XMLSerializer().serializeToString(clone)
}

function safeBaseName() {
  return (props.title || '思维导图').replace(/[\\/:*?"<>|\r\n]+/g, '_').slice(0, 60) || 'mindmap'
}

function exportSvg() {
  if (!svgEl.value) return
  const xml = buildStandaloneSvgString()
  const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml;charset=utf-8' }))
  triggerDownload(url, `${safeBaseName()}_思维导图.svg`)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
  emit('notify', 'SVG 矢量思维导图已导出')
}

function exportPng() {
  if (!svgEl.value) return
  const { width, height } = layout.value
  const xml = buildStandaloneSvgString()
  const svgBlob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(svgBlob)
  const img = new Image()
  img.onload = () => {
    const ratio = 2
    const canvas = document.createElement('canvas')
    canvas.width = width * ratio
    canvas.height = height * ratio
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    URL.revokeObjectURL(url)
    canvas.toBlob((blob) => {
      if (!blob) return
      const pngUrl = URL.createObjectURL(blob)
      triggerDownload(pngUrl, `${safeBaseName()}_思维导图.png`)
      setTimeout(() => URL.revokeObjectURL(pngUrl), 1500)
      emit('notify', '高清 PNG 思维导图已导出')
    }, 'image/png')
  }
  img.onerror = () => {
    URL.revokeObjectURL(url)
    emit('notify', '导出 PNG 失败，请尝试导出 SVG', 'error')
  }
  img.src = url
}

function exportMarkdown() {
  const url = URL.createObjectURL(new Blob([props.markdown || ''], { type: 'text/markdown;charset=utf-8' }))
  triggerDownload(url, `${safeBaseName()}_大纲导图.md`)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
  emit('notify', 'Markdown 导图大纲已导出（可导入 XMind / Obsidian）')
}

watch(() => props.markdown, () => {
  collapsed.value = new Set()
  nextTick(fitView)
})

onMounted(() => nextTick(fitView))
</script>

<template>
  <div class="overflow-hidden rounded-2xl border border-slate-200 bg-white">
    <!-- Toolbar -->
    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50/80 px-3 py-2 text-xs">
      <div class="flex flex-wrap items-center gap-1">
        <button type="button" class="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-600"
          title="缩小" @click="zoomBy(-0.15)">
          <LearnIcon name="minus" :size="14" />
        </button>
        <span class="min-w-[3.2rem] text-center font-semibold text-slate-600">{{ Math.round(scale * 100) }}%</span>
        <button type="button" class="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-600"
          title="放大" @click="zoomBy(0.15)">
          <LearnIcon name="plus" :size="14" />
        </button>
        <button type="button" class="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-600"
          @click="fitView">
          <LearnIcon name="expand" :size="13" /> 适应画布
        </button>
        <button type="button" class="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-600"
          @click="expandAll">
          展开全部
        </button>
        <button type="button" class="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-600"
          @click="collapseBranches">
          收起分支
        </button>
      </div>

      <div class="flex flex-wrap items-center gap-1.5">
        <button type="button" class="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-600"
          @click="showSource = !showSource">
          <LearnIcon name="code" :size="13" /> {{ showSource ? '脑图视图' : 'Markdown 大纲' }}
        </button>
        <button type="button" class="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-600"
          @click="exportPng">
          <LearnIcon name="download" :size="13" /> PNG
        </button>
        <button type="button" class="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-600"
          @click="exportSvg">
          SVG
        </button>
        <button type="button" class="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-indigo-300 hover:text-indigo-600"
          @click="exportMarkdown">
          MD
        </button>
      </div>
    </div>

    <!-- Outline source view -->
    <pre v-if="showSource" class="max-h-[440px] overflow-auto bg-slate-950 p-4 text-xs leading-6 text-slate-100">{{ markdown }}</pre>

    <!-- Interactive SVG Canvas -->
    <div v-else ref="canvas-wrap"
      class="mindmap-canvas relative h-[420px] w-full overflow-hidden sm:h-[480px]"
      :class="dragging ? 'cursor-grabbing' : 'cursor-grab'"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @wheel="onWheel">
      <svg ref="mindmap-svg" class="h-full w-full" style="font-family: ui-sans-serif, system-ui, 'PingFang SC', 'Microsoft YaHei', sans-serif">
        <g data-viewport :transform="`translate(${panX}, ${panY}) scale(${scale})`">
          <!-- Bezier Edges -->
          <path v-for="edge in layout.edges" :key="edge.id" :d="edge.d" fill="none"
            :stroke="edge.stroke" stroke-width="2" stroke-opacity="0.55" stroke-linecap="round" />

          <!-- Nodes -->
          <g v-for="node in layout.nodes" :key="node.id" :transform="`translate(${node.x}, ${node.y})`">
            <rect :width="node.boxW" :height="node.boxH" :rx="node.depth === 0 ? 12 : 9"
              :fill="node.color.fill" :stroke="node.color.stroke" :stroke-width="node.depth === 0 ? 0 : 1.5" />

            <!-- Multi-line Node Label -->
            <text :x="node.depth === 0 ? 18 : 14"
              :y="(node.boxH - (node.lines.length - 1) * node.lineH) / 2 + node.fontSize * 0.36"
              :fill="node.color.text" :font-size="node.fontSize" :font-weight="node.depth <= 1 ? '700' : '500'">
              <tspan v-for="(ln, li) in node.lines" :key="li" :x="node.depth === 0 ? 18 : 14" :dy="li === 0 ? 0 : node.lineH">{{ ln }}</tspan>
            </text>

            <!-- Clickable Timestamp Badge inside Node -->
            <g v-if="node.tsLabel" data-node-action="seek" class="cursor-pointer"
              :transform="`translate(${node.boxW - (node.hasChildren && node.depth > 0 ? 74 : 56)}, ${(node.boxH - 20) / 2})`"
              @click.stop="emit('seek', node.seekSec)">
              <rect width="46" height="20" rx="10" :fill="node.depth === 0 ? 'rgba(255,255,255,0.22)' : node.color.badge" />
              <text x="23" y="13.5" text-anchor="middle" :fill="node.depth === 0 ? '#ffffff' : node.color.stroke"
                font-size="10.5" font-weight="700">{{ node.tsLabel }}</text>
            </g>

            <!-- Collapse / Expand Handle -->
            <g v-if="node.hasChildren && node.depth > 0" data-node-action="toggle" class="cursor-pointer"
              :transform="`translate(${node.boxW - 16}, ${node.boxH / 2})`"
              @click.stop="toggleNode(node)">
              <circle r="8.5" fill="#ffffff" :stroke="node.color.stroke" stroke-width="1.5" />
              <text y="3.5" text-anchor="middle" :fill="node.color.stroke" font-size="11" font-weight="800">
                {{ node.isCollapsed ? node.children.length : '−' }}
              </text>
            </g>
          </g>
        </g>
      </svg>

      <div class="pointer-events-none absolute bottom-2.5 left-3 rounded-full bg-white/85 px-2.5 py-1 text-[11px] text-slate-500 shadow-sm backdrop-blur">
        拖拽平移 · 滚轮缩放 · 点击节点时间可跳播
      </div>
    </div>
  </div>
</template>
