import { expect, test, type Page } from '@playwright/test'

function project(id: string, title: string) {
  return {
    project: { id, version: 1, stage: 'storyboard-ready', input: { mode: 'import_script', story: title } },
    script: { title, scenes: [], shots: [{ id: `${id}-shot`, title: `${title}首镜`, order: 1,
      durationSec: 5, visualDescription: `${title}画面`, action: '推门', emotion: '平静', shotSize: '中景', dialogue: '', narration: '雨夜。' }] },
    visualAssets: [], audioAssets: [], jobs: [], timelines: {},
  }
}
const items = [project('store', '深夜便利店诡事'), project('bus', '暴雨末班车')]

async function setup(page: Page, mode: 'success' | 'error' | 'empty' = 'success') {
  const state = { mode, mutations: [] as string[], listReads: 0 }
  await page.route('**/api/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (!['GET', 'HEAD'].includes(request.method())) {
      state.mutations.push(path)
      return route.fulfill({ status: 400, json: { error: 'TEST_FORBIDS_MUTATIONS' } })
    }
    if (path === '/api/provider-config') return route.fulfill({ json: { text: { configured: false } } })
    if (path === '/api/visual-styles') return route.fulfill({ json: { items: [] } })
    if (path === '/api/projects') {
      state.listReads++
      if (state.mode === 'error') return route.fulfill({ status: 503, json: { error: 'OFFLINE' } })
      return route.fulfill({ json: state.mode === 'empty' ? [] : items })
    }
    const item = items.find(entry => path === `/api/projects/${entry.project.id}`)
    return route.fulfill({ json: item ?? {} })
  })
  await page.goto('/')
  return state
}

test('finds and opens an existing project, persists selection and never generates', async ({ page }, info) => {
  const state = await setup(page)
  expect(state.listReads).toBe(0)
  await page.getByRole('button', { name: '打开已有项目', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '打开已有项目' })
  await dialog.getByRole('searchbox', { name: '搜索项目' }).fill('便利店')
  await expect(dialog.getByRole('button', { name: /深夜便利店诡事/ })).toBeVisible()
  await expect(dialog.getByRole('button', { name: /暴雨末班车/ })).toHaveCount(0)
  await page.screenshot({ path: info.outputPath('project-picker-desktop.png') })
  await dialog.getByRole('button', { name: /深夜便利店诡事/ }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByLabel('当前项目')).toHaveText('深夜便利店诡事')
  await page.reload()
  await expect(page.getByLabel('当前项目')).toHaveText('深夜便利店诡事')
  await page.getByRole('button', { name: '剧本', exact: true }).click()
  await page.getByRole('textbox', { name: '镜头标题-store-shot', exact: true }).fill('旧项目未保存的草稿')
  await page.getByRole('button', { name: '打开已有项目', exact: true }).click()
  await expect(dialog.getByText(/切换前请先保存当前编辑/)).toBeVisible()
  await dialog.getByRole('searchbox').fill('bus')
  await dialog.getByRole('button', { name: /暴雨末班车/ }).click()
  await expect(page.getByLabel('当前项目')).toHaveText('暴雨末班车')
  await expect(page.getByRole('textbox', { name: '镜头标题-bus-shot', exact: true })).toHaveValue('暴雨末班车首镜')
  expect(state.mutations).toEqual([])
})

test('list failure supports explicit reload and narrow dialog closes with Escape', async ({ page }, info) => {
  const state = await setup(page, 'error')
  const open = page.getByRole('button', { name: '打开已有项目', exact: true })
  await open.click()
  const dialog = page.getByRole('dialog', { name: '打开已有项目' })
  await expect(dialog.getByRole('alert')).toContainText('项目列表读取失败')
  expect(state.listReads).toBe(1)
  state.mode = 'success'
  await dialog.getByRole('button', { name: '重新读取' }).click()
  await expect(dialog.getByRole('button', { name: /深夜便利店诡事/ })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: info.outputPath('project-picker-mobile.png') })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(open).toBeFocused()
  expect(state.mutations).toEqual([])
})

test('empty project list is explicit and does not change current project', async ({ page }) => {
  const state = await setup(page, 'empty')
  await page.getByRole('button', { name: '打开已有项目', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('还没有可打开的项目。')).toBeVisible()
  await page.getByRole('button', { name: '关闭项目列表' }).click()
  await expect(page.getByText('尚未选择项目', { exact: true })).toBeVisible()
  expect(state.mutations).toEqual([])
})
