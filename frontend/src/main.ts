import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router/index'
import './styles/variables.css'
import './styles/base.css'
import './styles/transitions.css'
import './styles/responsive.css'

createApp(App).use(router).mount('#app')
