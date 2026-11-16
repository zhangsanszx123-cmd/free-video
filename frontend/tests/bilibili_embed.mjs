import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { computed, effectScope, reactive, ref, watch } from 'vue'
import { bilibiliEmbedUrl } from '../src/learning/videoEmbed.js'

// Run each component's real setup and seek handler without mounting a remote player.
// Browser-level rendering is checked separately by the mocked UI regression suite.
globalThis.BroadcastChannel = class { postMessage() {} }
const timestampHelpers = await import('../src/learning/learnApi.js')

const BVID = 'BV1mAAmzqEfP'
const videoUrl = `https://www.bilibili.com/video/${BVID}/`

async function previewComponent(relativePath, rawUrl) {
  const source = await readFile(new URL(relativePath, import.meta.url), 'utf8')
  const setup = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const workbench = relativePath.includes('LearnWorkbench')
  const info = { url: rawUrl, title: 'Test video', qualities: [], duration: 600 }
  const lifecycle = []
  const scope = effectScope()
  const context = {
    computed, ref, watch,
    useTemplateRef: () => ref(null),
    onMounted() {},
    onUnmounted: (callback) => lifecycle.push(callback),
    defineProps: () => reactive({ info, activeView: 'ai' }),
    defineEmits: () => () => {},
    useRoute: () => ({ query: {} }),
    useRouter: () => ({ replace: async () => {} }),
    useParseRequest: () => ({ loading: ref(false), parse() {}, cancel() {} }),
    fmt: { duration: (seconds) => String(seconds) },
    ...timestampHelpers,
    bilibiliEmbedUrl,
  }
  const expose = workbench
    ? 'info.value = initialInfo; return { src: bilibiliIframeSrc, seek: handleSeek }'
    : 'return { src: bilibiliIframeSrc, seek: seekAiVideo }'
  const component = scope.run(() => new Function(...Object.keys(context), 'initialInfo', `${setup}\n${expose}`)(...Object.values(context), info))
  return {
    ...component,
    dispose() { lifecycle.forEach((callback) => callback()); scope.stop() },
  }
}

test('player URL accepts valid parts independently of query order and normalizes invalid positions', () => {
  for (const query of ['?p=3&spm_id_from=test', '?spm_id_from=test&p=3', '?p=03']) {
    for (const seconds of [-1, NaN, Infinity, 'invalid', Number.MAX_SAFE_INTEGER + 1]) {
      const iframe = new URL(bilibiliEmbedUrl({ bvid: BVID, url: videoUrl + query, seconds }))
      assert.equal(iframe.searchParams.get('p'), '3')
      assert.equal(iframe.searchParams.get('t'), '0')
      assert.equal(iframe.searchParams.has('spm_id_from'), false)
    }
  }
  assert.equal(new URL(bilibiliEmbedUrl({ bvid: BVID, url: 'invalid' })).searchParams.get('p'), '1')
  assert.equal(bilibiliEmbedUrl({ bvid: null, url: videoUrl }), '')
  assert.equal(bilibiliEmbedUrl({ bvid: 'invalid', url: videoUrl }), '')
})

for (const [entry, path] of [
  ['home result', '../src/components/ResultCard.vue'],
  ['learning workbench', '../src/learning/pages/LearnWorkbench.vue'],
]) {
  test(`${entry}: retain selected part initially and after timestamp seeking`, async () => {
    for (const part of [2, 3]) {
      const original = `${videoUrl}?spm_id_from=test&p=${part}&t=999`
      const component = await previewComponent(path, original)
      try {
        let iframe = new URL(component.src.value)
        assert.equal(iframe.origin, 'https://player.bilibili.com')
        assert.equal(iframe.searchParams.get('bvid'), BVID)
        assert.equal(iframe.searchParams.get('p'), String(part))
        assert.equal(iframe.searchParams.get('t'), '0')
        assert.equal(iframe.searchParams.get('autoplay'), '0')
        assert.equal(iframe.searchParams.has('cid'), false, 'cid would override the selected part')
        for (const [seek, expected] of [[125.9, '125'], [0, '0']]) {
          component.seek(seek)
          iframe = new URL(component.src.value)
          assert.equal(iframe.searchParams.get('p'), String(part))
          assert.equal(iframe.searchParams.get('t'), expected)
          assert.equal(iframe.searchParams.get('autoplay'), '1')
        }
        const platform = new URL(timestampHelpers.platformTimeUrl(original, 42))
        assert.equal(platform.searchParams.get('p'), String(part))
        assert.equal(platform.searchParams.get('t'), '42')
        assert.equal(original, `${videoUrl}?spm_id_from=test&p=${part}&t=999`)
      } finally {
        component.dispose()
      }
    }
  })

  test(`${entry}: missing or invalid part safely selects part one`, async () => {
    for (const query of ['', '?p=', '?p=0', '?p=-1', '?p=1.5', '?p=nope', '?p=NaN', '?p=Infinity', '?p=9007199254740992']) {
      const component = await previewComponent(path, videoUrl + query)
      try {
        const iframe = new URL(component.src.value)
        assert.equal(iframe.searchParams.get('p'), '1', query || 'no part')
        assert.equal(iframe.searchParams.get('autoplay'), '0')
      } finally {
        component.dispose()
      }
    }
  })
}
