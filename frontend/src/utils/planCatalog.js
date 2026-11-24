/* Copyright 2017-present, The Visdom Authors */
import { api } from '../context/AuthContext';
import { cachedGet } from './requestCache';

const catalogPath = '/billing/plans';

export const getPublicPlans = () => cachedGet(catalogPath, async () => {
  const response = await api.get(catalogPath, { timeout: 5000 });
  return response.data;
});
