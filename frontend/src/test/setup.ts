import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

// jsdom gaps the app touches on mount.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false }) as MediaQueryList
}
if (!('ResizeObserver' in window)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.assign(window, { ResizeObserver: ResizeObserverStub })
}
Element.prototype.scrollIntoView ??= () => {}

beforeEach(() => {
  // Tests never reach a backend: pin demo data so the live probe cannot flip the mode mid-test.
  window.localStorage.setItem('vouch.apiMode', 'mock')
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('fetch disabled in tests'))))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})
