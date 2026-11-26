import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router/index'
import { useTheme } from './composables/useTheme'
import { useMotionPrefs } from './composables/useMotionPrefs'
import './styles/variables.css'
import './styles/base.css'
import './styles/transitions.css'
import './styles/responsive.css'

// 首帧挂载前同步套用主题与低动态偏好，消除暗色首屏闪白
useTheme().loadTheme()
useMotionPrefs()

createApp(App).use(router).mount('#app')
