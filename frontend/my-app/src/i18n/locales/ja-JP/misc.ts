import enUS from '../en-US/misc';

// HTTP status and other translations - Japanese
export default {
  http: {
    ...enUS.http,
    400: 'リクエストパラメータエラー',
    401: '未認証、再度ログインしてください',
    403: 'アクセス拒否',
    404: 'リソースが見つかりません',
    500: 'サーバー内部エラー',
    502: 'ゲートウェイエラー',
    503: 'サービス利用不可',
    networkError: 'ネットワークエラー、接続を確認してください',
    timeout: 'リクエストタイムアウト',
  },

  coffee: {
    ...enUS.coffee,
    buyMeACoffee: 'コーヒーを買ってください',
    title: 'コーヒーを買ってください',
    message: '創作は簡単ではありません。このプロジェクトがお役に立てば、サポートしていただけると幸いです！心から感謝いたします！これは私がこのプロジェクトの開発を続けるための大きな原動力となります！',
    wechatPay: 'WeChat Pay',
    alipay: 'Alipay',
    thankYou: 'ご支援ありがとうございます！',
    contactMe: '連絡先',
  },
};
