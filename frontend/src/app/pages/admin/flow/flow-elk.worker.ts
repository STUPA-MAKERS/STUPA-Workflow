/**
 * The web worker of the flow layout (spec 003135). The ELK worker script sees that it runs in a
 * worker and answers the messages of `elk-api` itself, so ELK runs off the main thread and a
 * layout does not block input or drawing.
 */
import 'elkjs/lib/elk-worker.min.js';
