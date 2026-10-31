<template>
  <div class="login-page">
    <div class="ambient-grid" aria-hidden="true" />
    <div class="particle-field" aria-hidden="true">
      <span class="particle particle-1" />
      <span class="particle particle-2" />
      <span class="particle particle-3" />
      <span class="particle particle-4" />
      <span class="particle particle-5" />
      <span class="particle particle-6" />
      <span class="particle particle-7" />
      <span class="particle particle-8" />
      <span class="particle particle-9" />
      <span class="particle particle-10" />
      <span class="particle particle-11" />
      <span class="particle particle-12" />
    </div>

    <section class="login-panel panel-surface">
      <div class="panel-layout">
        <div class="panel-copy">
          <div class="panel-brand">
            <div class="brand-chip">{{ t('login.brand') }}</div>
            <h1>{{ t('login.h1') }}</h1>
            <p>{{ t('login.sub') }}</p>
          </div>

          <div class="panel-meta">
            <div class="meta-card">
              <span class="meta-label">{{ t('login.styleLabel') }}</span>
              <strong>{{ t('login.styleValue') }}</strong>
            </div>
            <div class="meta-card">
              <span class="meta-label">{{ t('login.capLabel') }}</span>
              <strong>{{ t('login.capValue') }}</strong>
            </div>
          </div>

          <div class="feature-strip">
            <div class="feature-item">
              <span class="feature-title">{{ t('login.featAuth') }}</span>
              <span class="feature-text">{{ t('login.featAuthText') }}</span>
            </div>
            <div class="feature-item">
              <span class="feature-title">{{ t('login.featEntry') }}</span>
              <span class="feature-text">{{ t('login.featEntryText') }}</span>
            </div>
          </div>
        </div>

        <div class="form-card">
          <div class="form-card-head">
            <span class="form-eyebrow">{{ t('login.eyebrow') }}</span>
            <h2>{{ t('login.formH2') }}</h2>
            <p>{{ t('login.formHint') }}</p>
          </div>

          <el-form class="login-form" @submit.prevent="submit">
            <div class="field-block">
              <label class="field-label" for="login-username">{{ t('login.username') }}</label>
              <el-input
                id="login-username"
                v-model.trim="username"
                size="large"
                :placeholder="t('login.usernamePh')"
                :prefix-icon="User"
                autocomplete="username"
                @keyup.enter="submit"
              />
            </div>

            <div class="field-block">
              <label class="field-label" for="login-password">{{ t('login.password') }}</label>
              <el-input
                id="login-password"
                v-model="password"
                size="large"
                type="password"
                :placeholder="t('login.passwordPh')"
                :prefix-icon="Lock"
                show-password
                autocomplete="current-password"
                @keyup.enter="submit"
              />
            </div>

            <div class="field-block">
              <div class="verify-head">
                <label class="field-label">{{ t('login.slider') }}</label>
                <el-button text size="small" :loading="sliderLoading" @click="loadSliderChallenge">{{ t('login.sliderRefresh') }}</el-button>
              </div>
              <div class="slider-shell" :class="{ verified: sliderVerified }">
                <SlideVerify
                  v-if="sliderReady"
                  :key="sliderChallengeId"
                  :l="42"
                  :r="10"
                  :w="310"
                  :h="155"
                  :accuracy="sliderAccuracy"
                  :offset="sliderOffset"
                  :imgs="sliderImages"
                  :show="false"
                  :slider-text="t('login.sliderText')"
                  @success="handleSlideSuccess"
                  @fail="handleSlideFail"
                  @again="handleSlideAgain"
                />
                <div v-else class="slider-loading">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  <span>{{ t('login.sliderLoading') }}</span>
                </div>
                <div class="slider-status" :class="{ pass: sliderVerified }">
                  {{ sliderVerified ? t('login.sliderPass') : t('login.sliderTodo') }}
                </div>
              </div>
            </div>

            <el-button
              class="submit-btn"
              type="primary"
              size="large"
              :loading="loading"
              :disabled="sliderLoading || !sliderVerified"
              @click="submit"
            >
              {{ t('login.submit') }}
            </el-button>

            <el-button
              v-if="demoEnabled"
              class="demo-btn"
              text
              size="large"
              :loading="demoLoading"
              @click="demoLogin"
            >
              {{ t('login.demo') }}
            </el-button>
          </el-form>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading, Lock, User } from '@element-plus/icons-vue'
import http from '@/utils/http'
import { setAuth } from '@/utils/auth'
import SlideVerify from 'vue3-slide-verify'
import 'vue3-slide-verify/dist/style.css'
import { useI18n } from '@/i18n'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const username = ref('')
const password = ref('')
const loading = ref(false)
const sliderLoading = ref(false)
const demoEnabled = ref(false)
const demoLoading = ref(false)
const sliderChallengeId = ref('')
const sliderValue = ref(0)
const sliderMin = ref(36)
const sliderMax = ref(260)
const sliderTarget = ref(120)
const sliderTolerance = ref(6)
const sliderVerified = ref(false)
/*
 * 首次挑战到手之前不挂载 SlideVerify。
 *
 * 组件在 setup 里解构 props（`const { ..., offset } = props`），offset 因此
 * 是一次性快照，只有重挂载才能生效。若先挂载、等挑战回来再靠 :key 立刻重挂载，
 * 旧实例的图片 onload 会在它被卸载之后才触发，而该回调里
 *     block.value.width = L
 * 此时 block.value 已是 null —— 就是控制台里的
 * "Cannot set properties of null (setting 'width')"。
 * 先取挑战、带着正确 offset 首次挂载，即可避免这次"刚挂载就重挂载"的竞态。
 */
const sliderReady = ref(false)

/*
 * vue3-slide-verify 的合法 offset 窗口 —— 必须精确复刻组件源码里的判据：
 *     const L = l + r * 2 + 3
 *     if (offset > 0 && !(offset >= L + 10 && offset <= w - (L + 10)))
 *         throw new Error(`offset must be greater than ${L + 10} ...`)
 * 一旦抛错，组件在绘制之前就中止，画布保持空白、拼图不可用、无法登录。
 * 取 l=42, r=10, w=310 时 L=65，窗口为 75..235。
 */
const SLIDE_CANVAS_WIDTH = 310
const SLIDE_BLOCK_LENGTH = 42
const SLIDE_BLOCK_RADIUS = 10
const SLIDE_OFFSET_L = SLIDE_BLOCK_LENGTH + SLIDE_BLOCK_RADIUS * 2 + 3
const SLIDE_MIN_OFFSET = SLIDE_OFFSET_L + 10
const SLIDE_MAX_OFFSET = SLIDE_CANVAS_WIDTH - (SLIDE_OFFSET_L + 10)

/*
 * 必须显式传入本地拼图底图，不能省。
 *
 * vue3-slide-verify 的 imgs 默认为空数组，此时它回落到内置外链
 *   "https://picsum.photos/300/150?image=" + 随机(0,1084)
 * 并且 createImg() 会设置 img.crossOrigin = "Anonymous"（因为要用 canvas
 * getImageData 抠拼图块），于是这些图片必然走 CORS 校验；一旦加载失败，
 * onerror 还会再随机换一张重试 —— 在内网/无外网环境下就是"报 CORS 错误 +
 * 无限重试 + 拼图空白"。
 *
 * 这几张图放在 assets/slider/ 下，构建后与页面同源，不依赖任何外网请求。
 */
const sliderImages = Object.entries(
  import.meta.glob('../assets/slider/*.{jpg,jpeg,png,webp}', {
    eager: true,
    query: '?url',
    import: 'default',
  }),
)
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([, url]) => url)

/**
 * 将后端下发的挑战目标换算为拼图初始偏移（像素）。
 */
const sliderOffset = computed(() => {
  const raw = Number(sliderTarget.value) || 0
  return Math.min(Math.max(Math.round(raw), SLIDE_MIN_OFFSET), SLIDE_MAX_OFFSET)
})

/**
 * 将后端 tolerance 换算为组件的拼合容差。
 */
const sliderAccuracy = computed(() => Math.max(Number(sliderTolerance.value) || 5, 1))

/**
 * 重置当前滑动验证状态。
 */
const resetSlider = () => {
  sliderValue.value = sliderMin.value
  sliderVerified.value = false
}

/**
 * 从后端获取新的滑动验证挑战。
 */
const loadSliderChallenge = async () => {
  // 重入锁：任何来源（mount、手动刷新、组件 @refresh）都不可并发或递归调用，
  // 兜底防止再次出现无限请求 /api/auth/slider 的情况。
  if (sliderLoading.value) return
  sliderLoading.value = true
  try {
    const res = await http.get('/api/auth/slider')
    if (res.data.code !== 200 || !res.data.data) {
      throw new Error(res.data.msg || t('login.msgSliderErr'))
    }
    sliderChallengeId.value = res.data.data.challenge_id
    sliderMin.value = Number(res.data.data.min) || SLIDE_MIN_OFFSET
    sliderMax.value = Number(res.data.data.max) || SLIDE_MAX_OFFSET
    sliderTarget.value = Number(res.data.data.target) || 120
    sliderTolerance.value = Number(res.data.data.tolerance) || 6
    resetSlider()
    // 挑战已就绪，允许挂载组件；此后 offset 变化靠 :key 重挂载生效。
    sliderReady.value = true
    // 不调用组件的 refresh()：它内部会 emit('refresh')，而 @refresh 又会回到
    // 本函数，形成 loadSliderChallenge → refresh → emit → 本函数 的无限递归，
    // 导致登录页不停请求 /api/auth/slider。
  } catch (error) {
    ElMessage.error(error?.response?.data?.msg || error?.message || t('login.msgSliderErr'))
  } finally {
    sliderLoading.value = false
  }
}

/**
 * 拼图成功：记录滑块移动距离作为回传后端的校验值。
 */
const handleSlideSuccess = (detail) => {
  sliderValue.value = Number(detail?.left) || 0
  sliderVerified.value = true
}

/**
 * 拼图失败：保持未通过状态，组件会自动复位。
 */
const handleSlideFail = () => {
  sliderVerified.value = false
  ElMessage.warning(t('login.msgSlideFail'))
}

/**
 * 检测到疑似非人为操作（机器滑动轨迹）。
 */
const handleSlideAgain = () => {
  sliderVerified.value = false
  ElMessage.warning(t('login.msgSlideAgain'))
}

/*
 * 不再绑定组件的 @refresh：刷新图标已由 :show="false" 关闭，而组件内部的
 * refresh() 会 emit('refresh')，保留该回调等于给
 * loadSliderChallenge → 重挂载 → emit('refresh') → loadSliderChallenge
 * 这条回路留后门。刷新统一走页面上方的「刷新验证」按钮。
 */

/**
 * 提交用户名密码并在成功后写入本地登录态。
 * 后端把凭证转发给第三方统一登录系统（密码 AES 加密传输），成功下发 JWT。
 */
const submit = async () => {
  if (!username.value || !password.value) {
    ElMessage.warning(t('login.msgUserPwd'))
    return
  }
  if (!sliderVerified.value || !sliderChallengeId.value) {
    ElMessage.warning(t('login.msgSliderFirst'))
    return
  }

  loading.value = true
  try {
    const res = await http.post('/api/auth/login', {
      username: username.value,
      password: password.value,
      slider_challenge_id: sliderChallengeId.value,
      slider_value: sliderValue.value,
    })

    if (res.data.code === 200) {
      setAuth(res.data.data.token, res.data.data.user)
      ElMessage.success(t('login.msgOk'))
      // 回到被踢出前的页面。只接受站内绝对路径，挡掉 //evil.com 这类外跳。
      const raw = String(route.query.redirect || '/')
      const redirect = raw.startsWith('/') && !raw.startsWith('//') ? raw : '/'
      router.replace(redirect)
    } else {
      ElMessage.error(res.data.msg || t('login.msgFail'))
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.msg || t('login.msgFail'))
    await loadSliderChallenge()
  } finally {
    loading.value = false
  }
}

/**
 * 检测后端是否开启了演示模式；开启则在登录页显示「演示模式」入口。
 */
const checkDemo = async () => {
  try {
    const res = await http.get('/api/auth/status', { timeout: 3000 })
    demoEnabled.value = Boolean(res.data?.demo)
  } catch {
    demoEnabled.value = false
  }
}

/**
 * 演示模式登录：跳过账号密码与滑动验证，后端直接下发本地签名 token。
 * 仅当后端 AGENTREE_DEMO_AUTH=on 时可用。
 */
const demoLogin = async () => {
  demoLoading.value = true
  try {
    const res = await http.post('/api/auth/demo')
    if (res.data.code === 200) {
      setAuth(res.data.data.token, res.data.data.user)
      ElMessage.success(t('login.msgDemoOk'))
      const raw = String(route.query.redirect || '/')
      const redirect = raw.startsWith('/') && !raw.startsWith('//') ? raw : '/'
      router.replace(redirect)
    } else {
      ElMessage.error(res.data.msg || t('login.msgDemoFail'))
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.msg || t('login.msgDemoOff'))
  } finally {
    demoLoading.value = false
  }
}

onMounted(() => {
  // 不再预热全部底图：图片数量多了之后（几十张）那会把所有图都拉一遍，
  // 而每次挂载实际只用一张。竞态已由 sliderReady 门控解决（先取挑战再挂载，
  // 刷新时才重挂载，此时旧实例的图早已加载完成）。
  loadSliderChallenge()
  checkDemo()
})
</script>

<style scoped>
.login-page {
  position: relative;
  height: 100vh;
  display: grid;
  place-items: center;
  padding: 40px;
  background:
    radial-gradient(circle at 12% 18%, rgba(34, 197, 138, 0.2), transparent 24%),
    radial-gradient(circle at 82% 24%, rgba(63, 181, 158, 0.16), transparent 18%),
    radial-gradient(circle at 70% 78%, rgba(45, 159, 114, 0.12), transparent 20%),
    linear-gradient(180deg, #fbfcfe 0%, #f2f7f4 100%);
  overflow: hidden;
}

.ambient-grid {
  position: absolute;
  inset: 0;
  opacity: 0.42;
  background-image:
    linear-gradient(rgba(134, 173, 158, 0.14) 1px, transparent 1px),
    linear-gradient(90deg, rgba(134, 173, 158, 0.14) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(circle at center, rgba(0, 0, 0, 0.88), transparent 88%);
  pointer-events: none;
}

.particle-field {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.particle {
  position: absolute;
  display: block;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.96) 0%, rgba(34, 197, 138, 0.32) 42%, transparent 74%);
  box-shadow: 0 0 18px rgba(34, 197, 138, 0.18);
  filter: blur(0.2px);
  opacity: 0.95;
  animation: particle-float linear infinite;
}

.particle::after {
  content: '';
  position: absolute;
  inset: 28%;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.9);
}

.particle-1 { top: 10%; left: 11%; width: 12px; height: 12px; animation-duration: 18s; animation-delay: -3s; }
.particle-2 { top: 20%; left: 26%; width: 20px; height: 20px; animation-duration: 22s; animation-delay: -7s; }
.particle-3 { top: 14%; left: 78%; width: 12px; height: 12px; animation-duration: 16s; animation-delay: -2s; }
.particle-4 { top: 34%; left: 88%; width: 16px; height: 16px; animation-duration: 24s; animation-delay: -6s; }
.particle-5 { top: 52%; left: 7%; width: 22px; height: 22px; animation-duration: 20s; animation-delay: -11s; }
.particle-6 { top: 48%; left: 22%; width: 10px; height: 10px; animation-duration: 15s; animation-delay: -5s; }
.particle-7 { top: 62%; left: 84%; width: 18px; height: 18px; animation-duration: 23s; animation-delay: -4s; }
.particle-8 { top: 76%; left: 17%; width: 14px; height: 14px; animation-duration: 17s; animation-delay: -9s; }
.particle-9 { top: 82%; left: 36%; width: 10px; height: 10px; animation-duration: 21s; animation-delay: -1s; }
.particle-10 { top: 70%; left: 72%; width: 24px; height: 24px; animation-duration: 25s; animation-delay: -8s; }
.particle-11 { top: 30%; left: 58%; width: 10px; height: 10px; animation-duration: 14s; animation-delay: -10s; }
.particle-12 { top: 88%; left: 91%; width: 14px; height: 14px; animation-duration: 19s; animation-delay: -12s; }

.login-panel {
  position: relative;
  z-index: 1;
  width: min(1200px, calc(100vw - 80px));
  padding: 0;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(248, 252, 250, 0.97) 100%);
}

.login-panel::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 4px;
  background: linear-gradient(90deg, rgba(34, 197, 138, 0.95), rgba(63, 181, 158, 0.78), rgba(79, 124, 255, 0.6));
}

.login-panel::after {
  content: '';
  position: absolute;
  right: -64px;
  top: -68px;
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(34, 197, 138, 0.13), rgba(34, 197, 138, 0));
  pointer-events: none;
}

.panel-layout {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(360px, 420px);
  align-items: stretch;
}

.panel-copy {
  padding: 44px 40px 38px;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.16), rgba(255, 255, 255, 0)),
    linear-gradient(180deg, rgba(244, 250, 247, 0.9), rgba(240, 247, 244, 0.72));
  border-right: 1px solid rgba(219, 236, 229, 0.76);
}

.panel-brand h1 {
  margin: 16px 0 12px;
  font-size: 40px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--text-primary);
}

.panel-brand p {
  color: var(--text-secondary);
}

.brand-chip {
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 0 14px;
  border: 1px solid rgba(34, 197, 138, 0.22);
  border-radius: 999px;
  color: #17a673;
  background: rgba(34, 197, 138, 0.09);
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.panel-meta {
  margin: 34px 0 28px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.meta-card {
  padding: 16px 16px 18px;
  border: 1px solid rgba(219, 236, 229, 0.92);
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(246, 251, 249, 0.96));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.meta-label {
  display: block;
  margin-bottom: 8px;
  color: var(--text-muted);
  font-size: 12px;
  letter-spacing: 0.04em;
}

.meta-card strong {
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.55;
}

.feature-strip {
  display: grid;
  gap: 12px;
}

.feature-item {
  padding: 14px 16px;
  border-radius: var(--radius-md);
  border: 1px solid rgba(219, 236, 229, 0.8);
  background: rgba(255, 255, 255, 0.62);
}

.feature-title {
  display: block;
  margin-bottom: 6px;
  color: var(--text-primary);
  font-weight: 600;
}

.feature-text {
  color: var(--text-secondary);
}

.form-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 40px 36px 34px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(246, 251, 249, 0.95));
}

.form-card-head {
  margin-bottom: 26px;
}

.form-eyebrow {
  display: inline-flex;
  align-items: center;
  height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(34, 197, 138, 0.08);
  color: #17a673;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.form-card-head h2 {
  margin: 14px 0 8px;
  font-size: 28px;
  line-height: 1.15;
  color: var(--text-primary);
}

.form-card-head p {
  margin: 0;
  color: var(--text-secondary);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.field-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.2;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.verify-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.slider-shell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid #dcefe5;
  border-radius: var(--radius-md);
  background: rgba(248, 252, 250, 0.92);
  /* 组件画布固定宽度，避免父级 flex 收缩导致拼图错位 */
  width: max-content;
  max-width: 100%;
}

.slider-shell.verified {
  border-color: rgba(45, 159, 114, 0.45);
  background: rgba(240, 251, 246, 0.96);
}
/* 首屏占位：尺寸与组件画布一致，避免挑战到达后布局跳动 */
.slider-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 310px;
  height: 155px;
  color: #62788c;
  font-size: 13px;
}

.slider-status {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.slider-status.pass {
  color: #2d9f72;
}

/* vue3-slide-verify 组件主题微调，贴合登录页浅绿风格 */
.slider-shell :deep(.slide-verify) {
  border-radius: 10px;
  overflow: hidden;
}

.slider-shell :deep(.slide-verify-slider) {
  border-radius: 8px;
}

.slider-shell :deep(.slide-verify-slider-mask-item) {
  background: rgba(34, 197, 138, 0.18);
}

.slider-shell :deep(.slide-verify-slider-text) {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.login-form :deep(.el-input),
.login-form :deep(.el-input__wrapper) {
  width: 100%;
}

.login-form :deep(.el-input__wrapper) {
  min-height: 46px;
  padding: 0 14px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 0 0 1px #dcefe5 inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px rgba(34, 197, 138, 0.9) inset,
    0 0 0 4px rgba(34, 197, 138, 0.08);
}

.submit-spacer {
  display: block;
}

.submit-btn {
  width: 100%;
  min-height: 46px;
  margin-top: 4px;
  font-weight: 600;
  letter-spacing: 0.04em;
  background: linear-gradient(135deg, #1fae7c, #2fbf8e);
  border-color: transparent;
}

.demo-btn {
  width: 100%;
  margin-top: 12px;
  color: var(--text-secondary);
}

@keyframes particle-float {
  0% {
    transform: translate3d(0, 0, 0) scale(0.96);
  }
  50% {
    transform: translate3d(0, -22px, 0) scale(1.08);
  }
  100% {
    transform: translate3d(0, 0, 0) scale(0.96);
  }
}

@media (max-width: 980px) {
  .login-page {
    padding: 24px;
    /* 单列堆叠后面板可能高于视口：改为可滚动 + 顶部安全对齐，
     * 避免居中把表单顶部裁出屏幕外且滚不回来 */
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    place-items: start center;
  }

  .login-panel {
    width: min(100%, 680px);
    /* 放得下时仍垂直居中；放不下时 margin 归零，从顶部开始滚 */
    margin-block: auto;
  }

  .panel-layout {
    grid-template-columns: 1fr;
  }

  .panel-copy {
    padding: 32px 28px 18px;
    border-right: none;
    border-bottom: 1px solid rgba(219, 236, 229, 0.76);
  }

  .form-card {
    padding: 28px;
  }
}

/* 小屏手机（≤480px）：进一步收紧内边距 */
@media (max-width: 480px) {
  .login-page {
    padding: 14px;
  }

  .panel-copy {
    padding: 24px 18px 14px;
  }

  .form-card {
    padding: 18px 16px;
  }
}
</style>
