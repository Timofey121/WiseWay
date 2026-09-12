import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import './styles/foundation.css'
import './app/shell.css'
import './features/auth/auth.css'

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Не найден корневой элемент приложения.')
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
