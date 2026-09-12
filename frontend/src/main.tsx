import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Не найден корневой элемент приложения.')
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
