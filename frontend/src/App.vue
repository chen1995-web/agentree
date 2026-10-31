<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import en from 'element-plus/es/locale/lang/en'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { getUser, clearAuth } from '@/utils/auth'
import { useI18n } from '@/i18n'

const router = useRouter()
const route = useRoute()
const userName = ref(getUser()?.username || '')
const activeTab = ref(route.path.startsWith('/team') ? '/team' : '/console')

const { t, locale, setLocale } = useI18n()

// Element Plus 组件文案跟随 i18n 语言切换（分页/确认框等内置文案）。
const epLocale = computed(() => (locale.value === 'zh' ? zhCn : en))

watch(() => route.path, (p) => {
  activeTab.value = p.startsWith('/team') ? '/team' : '/console'
})

function onTabChange(v) {
  router.replace(v)
}

function onUserCommand(cmd) {
  if (cmd === 'logout') {
    clearAuth()
    router.replace('/login')
  }
}

function toggleLang() {
  setLocale(locale.value === 'en' ? 'zh' : 'en')
}
</script>

<template>
  <el-config-provider :locale="epLocale">
    <div class="shell">
      <header class="topnav">
        <span class="brand-mark">🌳</span>
        <span class="topnav-brand">agentree</span>
        <el-radio-group v-model="activeTab" @change="onTabChange">
          <el-radio-button value="/console">{{ t('app.consoleTab') }}</el-radio-button>
          <el-radio-button value="/team">{{ t('app.teamTab') }}</el-radio-button>
        </el-radio-group>
        <span class="topnav-spacer" />
        <el-tooltip :title="t('lang.title')" placement="bottom">
          <el-button text class="lang-btn" @click="toggleLang">
            <span class="lang-globe">🌐</span>{{ t('lang.switch') }}
          </el-button>
        </el-tooltip>
        <el-dropdown v-if="userName" trigger="click" @command="onUserCommand">
          <span class="user-chip">
            <el-avatar :size="26" class="user-avatar">{{ userName[0].toUpperCase() }}</el-avatar>
            <span class="uname">{{ userName }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">{{ t('app.logout') }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </header>
      <!-- 不能把 class 直接放 router-view 上：会合并到子页面根元素，覆盖 el-container 的横向布局 -->
      <div class="shell-body">
        <router-view />
      </div>
    </div>
  </el-config-provider>
</template>
