/** Isolated Marked + DOMPurify renderer that safely upgrades [MM:SS] text nodes into seek buttons. */
import { Marked } from 'marked'
import DOMPurify from 'dompurify'
import { formatTs, parseTs } from './learnApi.js'

const mdInstance = new Marked({
  gfm: true,
  breaks: true,
})

const TS_TOKEN_RE = /\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g

export function renderLearningMarkdown(markdownText) {
  if (!markdownText) return ''
  const rawHtml = mdInstance.parse(String(markdownText))
  const cleanHtml = DOMPurify.sanitize(rawHtml)
  if (typeof DOMParser === 'undefined') return cleanHtml

  const doc = new DOMParser().parseFromString(cleanHtml, 'text/html')
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
  const targets = []
  let node
  while ((node = walker.nextNode())) {
    const parentTag = node.parentElement?.tagName
    if (parentTag === 'CODE' || parentTag === 'PRE' || parentTag === 'BUTTON') continue
    if (node.nodeValue && node.nodeValue.includes('[')) {
      targets.push(node)
    }
  }

  for (const textNode of targets) {
    const value = textNode.nodeValue || ''
    TS_TOKEN_RE.lastIndex = 0
    let match = TS_TOKEN_RE.exec(value)
    if (!match) continue

    const frag = doc.createDocumentFragment()
    let cursor = 0
    while (match) {
      const sec = parseTs(match[1])
      if (sec === null) {
        match = TS_TOKEN_RE.exec(value)
        continue
      }
      if (match.index > cursor) {
        frag.appendChild(doc.createTextNode(value.slice(cursor, match.index)))
      }
      const btn = doc.createElement('button')
      btn.type = 'button'
      btn.className = 'ts-pill'
      btn.setAttribute('data-seek', String(sec))
      const display = formatTs(sec)
      btn.setAttribute('title', `点击跳转至 ${display}`)
      btn.textContent = `▶ ${display}`
      frag.appendChild(btn)
      cursor = match.index + match[0].length
      match = TS_TOKEN_RE.exec(value)
    }
    if (cursor < value.length) {
      frag.appendChild(doc.createTextNode(value.slice(cursor)))
    }
    textNode.parentNode?.replaceChild(frag, textNode)
  }

  return doc.body.innerHTML
}
