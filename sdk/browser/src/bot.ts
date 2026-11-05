/**
 * Client-Side Automation & WebDriver Detection.
 */

export function detectClientAutomation(): boolean {
  if (typeof window === 'undefined') return false;

  try {
    // Standard WebDriver flag
    if (navigator && (navigator.webdriver || (navigator as any).__webdriver_script_fn)) {
      return true;
    }

    // Common headless/scraper global signatures
    const w = window as any;
    if (
      w._phantom ||
      w.__nightmare ||
      w.callPhantom ||
      w.Buffer ||
      w.Cypress ||
      w.__selenium_unwrapped ||
      w.__fxdriver_unwrapped
    ) {
      return true;
    }
  } catch {
    // Fail-open
  }

  return false;
}
