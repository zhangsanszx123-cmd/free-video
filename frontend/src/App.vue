<script setup>
import NavBar from './components/NavBar.vue'
import SiteFooter from './components/SiteFooter.vue'
import MobileCtaBar from './components/MobileCtaBar.vue'
import UpgradeModal from './components/UpgradeModal.vue'
</script>

<template>
  <div class="flex min-h-screen flex-col overflow-x-hidden">
    <NavBar />
    <main class="flex-1">
      <RouterView />
    </main>
    <SiteFooter />
    <MobileCtaBar />
    <UpgradeModal />
  </div>
</template>
