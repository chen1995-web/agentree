/**
 * agentree 前端 i18n —— 零依赖、响应式。
 *
 * 设计取舍（为什么不用 vue-i18n）：
 * - 界面文案总量小（几十个 key），自建一层比引入第三方依赖更可控、构建更稳；
 * - 通过一个 reactive 的 locale + t() 暴露，模板里 `{{ t('key') }}` 会自动追踪
 *   locale 变化并重渲染；
 * - Element Plus 自带 locale（en / zh-cn），用 <el-config-provider :locale> 跟随切换，
 *   无需翻译组件内置文案（分页、确认框等）。
 *
 * 默认英文（en），可在顶栏一键切到中文（zh），选择持久化到 localStorage。
 */
import { reactive, computed } from 'vue'
import { en } from './locales/en'
import { zh } from './locales/zh'

const dicts = { en, zh }
const LS_KEY = 'agentree_locale'

function detect() {
  try {
    const saved = localStorage.getItem(LS_KEY)
    if (saved && dicts[saved]) return saved
  } catch { /* localStorage 不可用时回落默认 */ }
  // 默认英文：作品集面向国际评审，首屏即英文。
  return 'en'
}

const state = reactive({ locale: detect() })

/** 切换语言并持久化；同时更新 <html lang>。 */
export function setLocale(l) {
  if (!dicts[l] || l === state.locale) {
    if (l === state.locale) syncHtmlLang()
    return
  }
  state.locale = l
  try { localStorage.setItem(LS_KEY, l) } catch { /* 忽略 */ }
  syncHtmlLang()
}

/** 在 en / zh 之间切换。 */
export function toggleLocale() {
  setLocale(state.locale === 'en' ? 'zh' : 'en')
}

function syncHtmlLang() {
  if (typeof document !== 'undefined') document.documentElement.lang = state.locale
}

/**
 * 取翻译：当前语言缺失时回落到英文，再缺失则原样返回 key。
 * 支持 {name} 形式的占位插值。
 */
export function t(key, params) {
  const d = dicts[state.locale] || dicts.en
  let s = d[key] != null ? d[key] : dicts.en[key]
  if (s == null) s = key
  if (params) {
    for (const [k, v] of Object.entries(params)) s = s.split(`{${k}}`).join(String(v))
  }
  return s
}

/** 当前 locale 的响应式只读引用（用于判断分支）。 */
export const locale = computed(() => state.locale)

/** 供组件使用：返回 { t, locale, setLocale, toggleLocale }。 */
export function useI18n() {
  return { t, locale, setLocale, toggleLocale }
}

syncHtmlLang()
