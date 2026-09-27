import { z } from 'zod';
import { textResult } from '../lib/bitrix.js';

export function registerContactTools(server, bitrix) {
  server.registerTool('list_contacts', {
    description: 'List/search Bitrix24 contacts.',
    inputSchema: z.object({
      nameContains: z.string().optional(), companyId: z.number().int().optional(),
      assignedById: z.number().int().optional(), start: z.number().int().nonnegative().default(0),
      limitPages: z.number().int().min(1).max(20).default(1)
    })
  }, async (args) => {
    const filter = {};
    if (args.nameContains) filter['%NAME'] = args.nameContains;
    if (args.companyId !== undefined) filter.COMPANY_ID = args.companyId;
    if (args.assignedById !== undefined) filter.ASSIGNED_BY_ID = args.assignedById;
    let start = args.start, pages = 0, total = null, hasMore = false;
    const items = [];
    while (pages < args.limitPages) {
      const data = await bitrix('crm.contact.list', {
        filter, select: ['ID','NAME','SECOND_NAME','LAST_NAME','COMPANY_ID','ASSIGNED_BY_ID','DATE_CREATE','DATE_MODIFY','PHONE','EMAIL'],
        order: { ID: 'DESC' }, start
      });
      items.push(...(data.result || [])); total = data.total ?? total; pages += 1;
      if (data.next === undefined || data.next === null) { hasMore = false; break; }
      start = data.next; hasMore = true;
    }
    return textResult({ items, total, returned: items.length, hasMore, next: hasMore ? start : null });
  });

  server.registerTool('get_contact', {
    description: 'Get one Bitrix24 contact by ID.',
    inputSchema: z.object({ id: z.number().int().positive() })
  }, async ({ id }) => textResult((await bitrix('crm.contact.get', { id })).result));
}
