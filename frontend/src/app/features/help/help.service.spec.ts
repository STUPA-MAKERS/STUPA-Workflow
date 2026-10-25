import { HelpService } from './help.service';

describe('HelpService', () => {
  /** The shell keeps the loaded dialog. */
  it('opens and closes the report dialog and remembers the first opening', () => {
    const help = new HelpService();
    expect(help.reportOpen()).toBe(false);
    expect(help.reportUsed()).toBe(false);
    help.openReport();
    expect(help.reportOpen()).toBe(true);
    expect(help.reportUsed()).toBe(true);
    help.closeReport();
    expect(help.reportOpen()).toBe(false);
    expect(help.reportUsed()).toBe(true);
  });
});
