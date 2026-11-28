/** Starts the web worker of the flow layout. The bundler finds the worker by this URL. */
export function spawnElkWorker(): Worker {
  return new Worker(new URL('./flow-elk.worker', import.meta.url), { type: 'module' });
}
