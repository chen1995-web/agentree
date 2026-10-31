import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// Element Plus 自带英文为默认语言；中文由 App.vue 的 <el-config-provider> 跟随
// i18n locale 切换（en / zh-cn），这里不再写死 locale。
import * as Icons from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(ElementPlus)
app.use(router)
for (const [name, comp] of Object.entries(Icons)) app.component(name, comp)
app.mount('#app')
