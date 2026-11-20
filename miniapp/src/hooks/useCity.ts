import Taro from '@tarojs/taro'
import { create } from 'zustand'

export interface City {
  code: string
  name: string
}

interface CityState {
  city: City | null
  setCity: (city: City) => void
}

const STORAGE_KEY = 'city'

function readCity(): City | null {
  const stored: unknown = Taro.getStorageSync(STORAGE_KEY)
  if (
    stored && typeof stored === 'object' && 'code' in stored && 'name' in stored &&
    typeof stored.code === 'string' && typeof stored.name === 'string' && stored.name
  ) {
    return { code: stored.code, name: stored.name }
  }
  return null
}

const useCityStore = create<CityState>((set) => ({
  city: readCity(),
  setCity(city) {
    Taro.setStorageSync(STORAGE_KEY, city)
    set({ city })
  },
}))

export default function useCity() {
  const { city, setCity } = useCityStore()
  return { city, setCity, regionCode: city?.code ?? '' }
}
