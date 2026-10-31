import { createRouter, createWebHashHistory } from 'vue-router'
import Console from '@/views/Console.vue'
import Login from '@/views/Login.vue'
import TeamView from '@/views/TeamView.vue'
import { isAuthed } from '@/utils/auth'

// Hash 路由：FastAPI 托管静态产物，无需服务端 rewrite 即可支持深链接。
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: Login, meta: { public: true } },
    { path: '/', redirect: '/console' },
    { path: '/console', name: 'console', component: Console },
    { path: '/team', name: 'team', component: TeamView },
  ],
})

router.beforeEach((to) => {
  if (to.meta.public) return true
  if (!isAuthed()) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
