import { createRouter, createWebHistory } from 'vue-router'
import Home from './pages/Home.vue'

const titles = {
  home: 'FreeVideo - 万能视频下载，1800+ 平台高清视频一键保存',
  batch: '批量下载打包 ZIP - FreeVideo',
  ai: 'AI 视频总结 & 字幕翻译 - FreeVideo',
  pricing: '会员定价 - FreeVideo Pro',
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Home },
    { path: '/batch', name: 'batch', component: () => import('./pages/Batch.vue') },
    { path: '/ai', name: 'ai', component: () => import('./pages/AiTools.vue') },
    { path: '/pricing', name: 'pricing', component: () => import('./pages/Pricing.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: (to) => (to.hash ? { el: to.hash, top: 80, behavior: 'smooth' } : { top: 0 }),
})

router.afterEach((to) => { document.title = titles[to.name] || titles.home })

export default router
