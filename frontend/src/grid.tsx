/* AG Grid (Community, MIT) set up once with Ringside's Ledger theme. */

import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'

ModuleRegistry.registerModules([AllCommunityModule])

export const ledgerTheme = themeQuartz.withParams({
  fontFamily: "'Inter Variable', ui-sans-serif, system-ui, sans-serif",
  fontSize: 13.5,
  dataFontSize: 13.5,
  headerFontSize: 12,
  headerFontWeight: 600,
  backgroundColor: '#fffdf8',
  foregroundColor: '#16202f',
  chromeBackgroundColor: '#f8f4ea',
  headerBackgroundColor: '#f3eee3',
  headerTextColor: '#5b6170',
  borderColor: '#e4ddcd',
  rowBorder: { color: '#ece6d8' },
  columnBorder: false,
  wrapperBorder: { color: '#e4ddcd' },
  wrapperBorderRadius: 12,
  rowHoverColor: '#f5efe2',
  selectedRowBackgroundColor: '#e5ebfb',
  oddRowBackgroundColor: '#fffdf8',
  accentColor: '#1f4fd8',
  rowHeight: 54,
  headerHeight: 42,
  cellHorizontalPadding: 16,
  spacing: 7,
  browserColorScheme: 'light',
})

/** Tiny CSV helper name, so exports are dated and recognisable. */
export function exportName(kind: string): string {
  return `ringside-${kind}-${new Date().toISOString().slice(0, 10)}.csv`
}
