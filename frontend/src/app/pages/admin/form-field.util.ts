/**
 * Form-builder helpers: the kit copies (`@stupa-makers/ui-kit/views/form-editor`, kit spec
 * 002278). The rules mirror `config_schemas.FormFieldDef`; the server validates again on save
 * and stays authoritative.
 */
export {
  FIELD_TYPES,
  KEY_PATTERN,
  PROMOTE_TARGETS,
  type FieldValidationResult,
  type QuestionGroup,
  type QuestionPos,
  blankField,
  blankOption,
  duplicateKeys,
  fundingProblem,
  groupsFromFields,
  groupsToFields,
  moveQuestionTo,
  normalizeFormField,
  participantsProblem,
  validateFormField,
  validateJsonLogic,
} from '@stupa-makers/ui-kit/views/form-editor';
