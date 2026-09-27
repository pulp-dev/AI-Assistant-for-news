import { z } from 'zod';
import { textResult } from '../lib/bitrix.js';

export function registerCompanyTools(server, bitrix) {
  server.registerTool('list_companies', {
    description: 'List/search Bitrix24 companies.',
    inputSchema: z.object({
      titleContains: z.string().optional(), assignedById: z.number().int().optional(),
      dateCreateFrom: z.string().optional(), dateCreateTo: z.string().optional(),
      start: z.number().int().nonnegative().default(0), limitPages: z.number().int().min(1).max(20).default(1)
    })
  }, async (args) => {
    const filter = {};
    if (args.titleContains) filter['%TITLE'] = args.titleContains;
    if (args.assignedById !== undefined) filter.ASSIGNED_BY_ID = args.assignedById;
    if (args.dateCreateFrom) filter['>=DATE_CREATE'] = args.dateCreateFrom;
    if (args.dateCreateTo) filter['<=DATE_CREATE'] = args.dateCreateTo;
    let start = args.start, pages = 0, total = null, hasMore = false;
    const items = [];
    while (pages < args.limitPages) {
      const data = await bitrix('crm.company.list', {
        filter, select: ['ID','TITLE','COMPANY_TYPE','INDUSTRY','EMPLOYEES','ASSIGNED_BY_ID','DATE_CREATE','DATE_MODIFY','PHONE','EMAIL'],
        order: { ID: 'DESC' }, start
      });
      items.push(...(data.result || [])); total = data.total ?? total; pages += 1;
      if (data.next === undefined || data.next === null) { hasMore = false; break; }
      start = data.next; hasMore = true;
    }
    return textResult({ items, total, returned: items.length, hasMore, next: hasMore ? start : null });
  });

  server.registerTool('get_company', {
    description: 'Get one Bitrix24 company by ID.',
    inputSchema: z.object({ id: z.number().int().positive() })
  }, async ({ id }) => textResult((await bitrix('crm.company.get', { id })).result));
}
