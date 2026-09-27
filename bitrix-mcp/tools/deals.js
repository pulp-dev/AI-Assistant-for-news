import { z } from 'zod';
import { textResult } from '../lib/bitrix.js';

export function registerDealTools(server, bitrix) {
  server.registerTool('list_deals', {
    description: 'List/search Bitrix24 deals with optional filters.',
    inputSchema: z.object({
      categoryId: z.number().int().optional(), stageId: z.string().optional(),
      assignedById: z.number().int().optional(), companyId: z.number().int().optional(),
      titleContains: z.string().optional(), dateCreateFrom: z.string().optional(),
      dateCreateTo: z.string().optional(), start: z.number().int().nonnegative().default(0),
      limitPages: z.number().int().min(1).max(20).default(1)
    })
  }, async (args) => {
    const filter = {};
    if (args.categoryId !== undefined) filter.CATEGORY_ID = args.categoryId;
    if (args.stageId) filter.STAGE_ID = args.stageId;
    if (args.assignedById !== undefined) filter.ASSIGNED_BY_ID = args.assignedById;
    if (args.companyId !== undefined) filter.COMPANY_ID = args.companyId;
    if (args.titleContains) filter['%TITLE'] = args.titleContains;
    if (args.dateCreateFrom) filter['>=DATE_CREATE'] = args.dateCreateFrom;
    if (args.dateCreateTo) filter['<=DATE_CREATE'] = args.dateCreateTo;

    let start = args.start, pages = 0, total = null, hasMore = false;
    const items = [];
    while (pages < args.limitPages) {
      const data = await bitrix('crm.deal.list', {
        filter,
        select: ['ID','TITLE','CATEGORY_ID','STAGE_ID','OPPORTUNITY','CURRENCY_ID','COMPANY_ID','CONTACT_ID','ASSIGNED_BY_ID','DATE_CREATE','DATE_MODIFY','CLOSEDATE','OPENED','CLOSED'],
        order: { ID: 'DESC' }, start
      });
      items.push(...(data.result || []));
      total = data.total ?? total;
      pages += 1;
      if (data.next === undefined || data.next === null) { hasMore = false; break; }
      start = data.next; hasMore = true;
    }
    return textResult({ items, total, returned: items.length, hasMore, next: hasMore ? start : null });
  });

  server.registerTool('get_deal', {
    description: 'Get one Bitrix24 deal by ID.',
    inputSchema: z.object({ id: z.number().int().positive() })
  }, async ({ id }) => textResult((await bitrix('crm.deal.get', { id })).result));

  server.registerTool('update_deal', {
    description: 'Update selected fields of one Bitrix24 deal.',
    inputSchema: z.object({ id: z.number().int().positive(), fields: z.record(z.any()) })
  }, async ({ id, fields }) => textResult(await bitrix('crm.deal.update', { id, fields })));

  server.registerTool('list_deal_categories', {
    description: 'List Bitrix24 deal funnels/categories.', inputSchema: z.object({})
  }, async () => textResult((await bitrix('crm.dealcategory.list', {})).result));

  server.registerTool('list_deal_stages', {
    description: 'List stages for a deal funnel.',
    inputSchema: z.object({ categoryId: z.number().int().nonnegative() })
  }, async ({ categoryId }) => {
    const entityId = categoryId === 0 ? 'DEAL_STAGE' : `DEAL_STAGE_${categoryId}`;
    return textResult((await bitrix('crm.status.list', { filter: { ENTITY_ID: entityId } })).result);
  });

  server.registerTool('count_deals_by_stage', {
    description: 'Count deals in a funnel grouped by stage.',
    inputSchema: z.object({ categoryId: z.number().int().nonnegative(), maxPages: z.number().int().min(1).max(100).default(100) })
  }, async ({ categoryId, maxPages }) => {
    let start = 0, pages = 0, total = 0, truncated = false;
    const counts = {};
    while (pages < maxPages) {
      const data = await bitrix('crm.deal.list', {
        filter: { CATEGORY_ID: categoryId }, select: ['ID','STAGE_ID'], order: { ID: 'ASC' }, start
      });
      for (const item of data.result || []) {
        const stage = item.STAGE_ID || 'UNKNOWN';
        counts[stage] = (counts[stage] || 0) + 1; total += 1;
      }
      pages += 1;
      if (data.next === undefined || data.next === null) break;
      start = data.next;
      if (pages >= maxPages) truncated = true;
    }
    return textResult({ categoryId, totalRead: total, counts, truncated });
  });
}
