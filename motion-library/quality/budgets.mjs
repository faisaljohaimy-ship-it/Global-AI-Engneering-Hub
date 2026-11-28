export const DEFAULT_BUDGETS = Object.freeze({
  performance_min: 95,
  accessibility_min: 95,
  lcp_ms_max: 2500,
  cls_max: 0.1,
  critical_axe_max: 0,
});

export function validateAuditUrl(input, expectedOrigin) {
  const url = new URL(input);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
      || url.username || url.password || url.hash
      || !/^\/motion-studio\/(?:index\.html)?$/.test(url.pathname)
      || (expectedOrigin && url.origin !== expectedOrigin)) {
    throw new Error('Audit URL must be the local Motion Studio entry point');
  }
  // Query strings are bounded fixture selectors, never remote resource locations.
  if (url.search.length > 200 || [...url.searchParams].some(([key, value]) =>
    !['motion', 'fixture'].includes(key) || !/^[a-zA-Z0-9_-]{1,80}$/.test(value))) {
    throw new Error('Unsupported Motion Studio query');
  }
  return url.href;
}

export function evaluateBudgets(metrics, budgets = DEFAULT_BUDGETS) {
  const checks = [
    ['performance_min', 'performance', 'min', 0, 100],
    ['accessibility_min', 'accessibility', 'min', 0, 100],
    ['lcp_ms_max', 'lcp_ms', 'max', 1, 10000],
    ['cls_max', 'cls', 'max', 0, 1],
    ['critical_axe_max', 'critical_axe', 'max', 0, 0],
  ];
  const failures = [];
  for (const [limit, field, direction, minimum, maximum] of checks) {
    const bound = budgets[limit];
    if (!Number.isFinite(bound) || bound < minimum || bound > maximum) {
      throw new Error(`Invalid finite budget: ${limit}`);
    }
    const value = metrics[field];
    if (!Number.isFinite(value) || value < 0 || (direction === 'min' ? value < bound : value > bound)) {
      failures.push({ metric: field, actual: Number.isFinite(value) ? value : null, budget: bound, direction });
    }
  }
  if (metrics.page_errors !== 0) failures.push({ metric: 'page_errors', actual: metrics.page_errors ?? null, budget: 0 });
  if (metrics.blocked_external_requests !== 0) failures.push({ metric: 'blocked_external_requests', actual: metrics.blocked_external_requests ?? null, budget: 0 });
  return { passed: failures.length === 0, failures };
}
