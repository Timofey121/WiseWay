import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from '../src/App'

describe('App', () => {
  it('отображает оболочку с заголовком WiseWay', () => {
    render(<App />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'WiseWay',
    )
  })
})
