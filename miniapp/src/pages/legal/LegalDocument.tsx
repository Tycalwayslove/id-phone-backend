import type { PropsWithChildren } from 'react'
import { Text, View } from '@tarojs/components'
import PageContainer from '../../components/PageContainer'
import './index.scss'

interface LegalSection {
  title: string
  body: string
}

interface Props extends PropsWithChildren {
  title: string
  sections: LegalSection[]
}

export default function LegalDocument({ title, sections, children }: Props) {
  return (
    <PageContainer>
      {children}
      <View className='card legal-document'>
        <Text className='legal-document__notice'>正文待法务确认</Text>
        <Text className='legal-document__title'>{title}</Text>
        {sections.map((section) => (
          <View key={section.title} className='legal-document__section'>
            <Text className='legal-document__heading'>{section.title}</Text>
            <Text className='legal-document__body'>{section.body}</Text>
          </View>
        ))}
      </View>
    </PageContainer>
  )
}
