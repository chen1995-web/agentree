import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

/**
 * 滚动跟随：内容增长时自动滚到底部；用户主动上滚即暂停跟随，
 * 重新滚回底部（阈值内）自动恢复跟随。
 *
 * @param getEl      () => HTMLElement 实际滚动容器（如卡片体）
 * @param source     watch 的数据源（如 () => store.events.length）
 * @param threshold  判定"在底部"的像素容差
 */
export function useAutoScroll(getEl, source, threshold = 48) {
  const pinned = ref(true) // true = 跟随底部
  let scroller = null
  let detach = null

  const bind = () => {
    const el = getEl()
    if (!el || el === scroller) return el
    if (detach) detach()
    scroller = el
    const onScroll = () => {
      pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight <= threshold
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    detach = () => el.removeEventListener('scroll', onScroll)
    return el
  }

  const scrollToBottom = () => {
    const el = bind()
    if (el) el.scrollTop = el.scrollHeight
  }

  watch(source, () => {
    const el = bind()
    if (!el || !pinned.value) return
    // flush post + rAF：等本次事件渲染完成后再贴底
    requestAnimationFrame(() => { el.scrollTop = el.scrollHeight })
  }, { flush: 'post' })

  onMounted(() => {
    bind()
    scrollToBottom()
  })
  onBeforeUnmount(() => detach && detach())

  return { pinned, scrollToBottom }
}
