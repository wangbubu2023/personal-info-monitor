export const sourceKeys = {
  all: ['sources'] as const,
  lists: () => [...sourceKeys.all, 'list'] as const,
  list: (params: Record<string, unknown>) => [...sourceKeys.lists(), params] as const,
}
