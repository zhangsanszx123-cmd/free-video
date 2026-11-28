import { createRouter, createWebHistory } from 'vue-router'
import Home from './pages/Home.vue'
import { account, openAuth, safeRedirect } from './account.js'
import { adminAuth, safeAdminRedirect } from './admin/adminAuth.js'
import { applyRouteSeo } from './seo.js'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/account/api', name: 'apiKeys', component: () => import('./pages/ApiKeys.vue'), meta: { requiresAuth: true } },
    { path: '/account/api/docs', name: 'apiDocs', component: () => import('./pages/ApiDocs.vue') },
    { path: '/admin/login', name: 'adminLogin', component: () => import('./admin/pages/AdminLogin.vue'), meta: { admin: true, adminGuestOnly: true } },
    { path: '/admin', component: () => import('./admin/AdminLayout.vue'), meta: { admin: true, requiresAdmin: true }, children: [
      { path: '', redirect: '/admin/users' },
      { path: 'users', name: 'adminUsers', component: () => import('./admin/pages/AdminUsers.vue') },
      { path: 'staff', name: 'adminStaff', component: () => import('./admin/pages/AdminStaff.vue'), meta: { superadmin: true } },
      { path: 'pricing', name: 'adminPricing', component: () => import('./admin/pages/AdminPricing.vue') },
      { path: 'limits', name: 'adminLimits', component: () => import('./admin/pages/AdminLimits.vue') },
      { path: 'history', name: 'adminHistory', component: () => import('./admin/pages/AdminHistory.vue') },
      { path: ':pathMatch(.*)*', name: 'adminNotFound', component: () => import('./admin/pages/AdminNotFound.vue') },
    ] },
    { path: '/', name: 'home', component: Home },
    // Guests may open these pages; the login dialog appears only when they actually start something.
    { path: '/batch', name: 'batch', component: () => import('./pages/Batch.vue') },
    { path: '/ai', name: 'ai', component: () => import('./pages/AiTools.vue') },
    { path: '/learn', name: 'learn', component: () => import('./learning/pages/LearnWorkbench.vue') },
    { path: '/pricing', name: 'pricing', component: () => import('./pages/Pricing.vue') },
    { path: '/login', name: 'login', component: () => import('./pages/Login.vue'), meta: { guestOnly: true } },
    { path: '/register', name: 'register', component: () => import('./pages/Register.vue'), meta: { guestOnly: true } },
    { path: '/verify-email', name: 'verifyEmail', component: () => import('./pages/VerifyEmail.vue') },
    { path: '/forgot-password', name: 'forgotPassword', component: () => import('./pages/PasswordRecovery.vue') },
    { path: '/reset-password', name: 'resetPassword', component: () => import('./pages/PasswordRecovery.vue') },
    { path: '/account', name: 'account', component: () => import('./pages/Account.vue'), meta: { requiresAuth: true } },
    { path: '/history', name: 'history', component: () => import('./pages/History.vue'), meta: { requiresAuth: true } },
    { path: '/pay/result', name: 'payResult', component: () => import('./pages/PayResult.vue'), meta: { requiresAuth: true } },
    { path: '/:pathMatch(.*)*', name: 'notFound', component: () => import('./pages/NotFound.vue') },
  ],
  scrollBehavior: (to) => (to.hash && !['verifyEmail', 'resetPassword'].includes(to.name) ? { el: to.hash, top: 80, behavior: 'smooth' } : { top: 0 }),
})

/** Route guard is only for UX; the backend validates the session on every protected API. */
router.beforeEach(async (to, from) => {
  if (to.meta.admin) {
    await adminAuth.ensure()
    if (to.meta.requiresAdmin && !adminAuth.loggedIn) return { name: 'adminLogin', query: { redirect: to.fullPath } }
    if (to.meta.adminGuestOnly && adminAuth.loggedIn) return safeAdminRedirect(to.query.redirect)
    if (to.meta.superadmin && !adminAuth.isSuperadmin) {
      adminAuth.notice = '当前后台账号无权管理后台账号'
      return { name: 'adminUsers' }
    }
    return true
  }
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

router.afterEach((to) => { applyRouteSeo(to) })

export default router
