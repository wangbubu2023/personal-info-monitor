import api from './api'
import type { Category, CategoryCreate } from '../types'

export const categoriesApi = {
  // List categories
  list: async (flat?: boolean): Promise<Category[]> => {
    const response = await api.get('/categories', { params: { flat } })
    return response.data
  },

  // Get single category
  get: async (id: string): Promise<Category> => {
    const response = await api.get(`/categories/${id}`)
    return response.data
  },

  // Create category
  create: async (data: CategoryCreate): Promise<Category> => {
    const response = await api.post('/categories', data)
    return response.data
  },

  // Update category
  update: async (id: string, data: Partial<CategoryCreate>): Promise<Category> => {
    const response = await api.patch(`/categories/${id}`, data)
    return response.data
  },

  // Delete category
  delete: async (id: string): Promise<void> => {
    await api.delete(`/categories/${id}`)
  },
}
