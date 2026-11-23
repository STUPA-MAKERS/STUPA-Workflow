/**
 * Guard/action read helpers shared by the flow editor and its child components. They are in
 * the kit (`/views/flow-editor`, ui-kit 002277), next to the inspectors that read them.
 */
export {
  actionParamOf,
  compareSpecOf,
  defaultGuard,
  groupsOf,
  guardBoolOf,
  guardOpOf,
  guardValueKind,
  guardValueOf,
  isBoolGuardOp,
  outDots,
  recipientNeedsRef,
  recipientsOf,
  sortedBranchDots,
} from '@stupa-makers/ui-kit/views/flow-editor';
