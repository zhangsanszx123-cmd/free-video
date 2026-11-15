import { createRouter, createWebHistory } from 'vue-router'
import Home from './pages/Home.vue'
import { account, openAuth, safeRedirect } from './account.js'

const titles = {
  home: 'FreeVideo - 万能视频下载，1800+ 平台高清视频一键保存',
  batch: '批量字幕提取与素材下载 - FreeVideo',
  ai: 'AI 视频总结 & 字幕翻译 - FreeVideo',
  learn: 'AI 视频学习工作台 - 大纲总结 · 思维导图 · 视频追问 - FreeVideo',
  pricing: '会员定价 - FreeVideo Pro',
  login: '登录 - FreeVideo',
  register: '注册账号 - FreeVideo',
  account: '个人中心 - FreeVideo',
  history: '任务记录 - FreeVideo',
  payResult: '支付结果 - FreeVideo',
  notFound: '页面不存在 - FreeVideo',
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Home },
    // Guests may open these pages; the login dialog appears only when they actually start something.
    { path: '/batch', name: 'batch', component: () => import('./pages/Batch.vue') },
    { path: '/ai', name: 'ai', component: () => import('./pages/AiTools.vue') },
    { path: '/learn', name: 'learn', component: () => import('./learning/pages/LearnWorkbench.vue') },
    { path: '/pricing', name: 'pricing', component: () => import('./pages/Pricing.vue') },
    { path: '/login', name: 'login', component: () => import('./pages/Login.vue'), meta: { guestOnly: true } },
    { path: '/register', name: 'register', component: () => import('./pages/Register.vue'), meta: { guestOnly: true } },
    { path: '/account', name: 'account', component: () => import('./pages/Account.vue'), meta: { requiresAuth: true } },
    { path: '/history', name: 'history', component: () => import('./pages/History.vue'), meta: { requiresAuth: true } },
    { path: '/pay/result', name: 'payResult', component: () => import('./pages/PayResult.vue'), meta: { requiresAuth: true } },
    { path: '/:pathMatch(.*)*', name: 'notFound', component: () => import('./pages/NotFound.vue') },
  ],
  scrollBehavior: (to) => (to.hash ? { el: to.hash, top: 80, behavior: 'smooth' } : { top: 0 }),
})

/** Route guard is only for UX; the backend validates the session on every protected API. */
router.beforeEach(async (to, from) => {
  if (!to.meta.requiresAuth && !to.meta.guestOnly) return true
  await account.ensure()
  // status 'error' (account service unreachable) counts as logged out; the dialog shows the error and a retry.
  if (to.meta.requiresAuth && !account.loggedIn) {
    openAuth({ notice: '请先登录后使用该功能', redirect: to.fullPath })
    // In-app navigation: stay on the current page under the dialog. First load (no current page): go home.
    return from.matched.length ? false : { path: '/', replace: true }
  }
  if (to.meta.guestOnly && account.loggedIn) return safeRedirect(to.query.redirect)
  return true
})

router.afterEach((to) => { document.title = titles[to.name] || titles.home })

export default router
