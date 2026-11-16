/** Build the Bilibili preview shared by the home result and learning workbench.
 * Official parameters: https://player.bilibili.com/ (p starts at 1; cid overrides p).
 */
export function bilibiliEmbedUrl({ bvid, url, seconds = 0, autoplay = false }) {
  if (!/^BV[0-9A-Za-z]{10}$/.test(bvid || '')) return ''

  let part = 1
  try {
    const value = new URL(url).searchParams.get('p') || ''
    const selected = Number(value)
    if (/^\d+$/.test(value) && Number.isSafeInteger(selected) && selected > 0) part = selected
  } catch { /* A missing or malformed source URL uses the first part. */ }

  const position = Math.floor(Number(seconds))
  const params = new URLSearchParams({
    bvid,
    p: String(part),
    high_quality: '1',
    danmaku: '0',
    autoplay: autoplay ? '1' : '0',
    t: String(Number.isSafeInteger(position) && position > 0 ? position : 0),
  })
  return `https://player.bilibili.com/player.html?${params}`
}
