import { useState } from 'react';
import { X, Send, Mail, Tv } from 'lucide-react';
import { useTranslation } from '../stores/i18nStore';
import { useSidebar } from '../contexts/SidebarContext';

export default function CoffeeButton() {
  const [isOpen, setIsOpen] = useState(false);
  const { t } = useTranslation();
  const { isCollapsed } = useSidebar();

  const contacts = [
    {
      icon: Send,
      name: 'Telegram',
      value: '@qianzhiwei',
      url: 'https://t.me/qianzhiwei',
      color: 'bg-blue-500',
    },
    {
      icon: Mail,
      name: 'E-mail',
      value: 'qianzhiwei5921@gmail.com',
      url: 'mailto:qianzhiwei5921@gmail.com',
      color: 'bg-red-500',
    },
    {
      icon: Tv,
      name: 'Bilibili',
      value: '钱神仙',
      url: 'https://space.bilibili.com/523189446',
      color: 'bg-pink-500',
    },
  ];

  return (
    <>
      {/* GitHub Link Button - Hidden when sidebar is collapsed */}
      {!isCollapsed && (
        <a
          href="https://github.com/qzw881130/AI-NovelFlow"
          target="_blank"
          rel="noopener noreferrer"
          className="group fixed bottom-4 left-[180px] z-[100] flex h-10 w-10 items-center justify-center rounded-full bg-gray-900 text-white shadow-lg transition-all hover:bg-gray-800 hover:shadow-xl lg:bottom-6 lg:left-[192px]"
          title="GitHub"
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
          </svg>
        </a>
      )}

      {/* Coffee Button - Hidden when sidebar is collapsed */}
      {!isCollapsed && (
        <button
          onClick={() => setIsOpen(true)}
          className="group fixed bottom-4 left-4 z-[100] flex items-center gap-2 rounded-full bg-amber-600 px-4 py-2 text-sm font-medium text-white shadow-lg transition-all hover:bg-amber-700 hover:shadow-xl lg:bottom-6 lg:left-6"
        >
          {/* Animated Coffee Cup Icon */}
          <div className="relative">
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              {/* Coffee Cup */}
              <path
                d="M18 8H19C20.1046 8 21 8.89543 21 10C21 11.1046 20.1046 12 19 12H18V8Z"
                fill="currentColor"
                className="opacity-80"
              />
              <path
                d="M2 8H18V14C18 16.2091 16.2091 18 14 18H6C3.79086 18 2 16.2091 2 14V8Z"
                fill="currentColor"
              />
              {/* Saucer */}
              <path
                d="M5 20H15C15.5523 20 16 20.4477 16 21C16 21.5523 15.5523 22 15 22H5C4.44772 22 4 21.5523 4 21C4 20.4477 4.44772 20 5 20Z"
                fill="currentColor"
                className="opacity-60"
              />
            </svg>
            {/* Steam Animation */}
            <div className="absolute -top-3 left-1/2 flex -translate-x-1/2 gap-0.5">
              <span
                className="h-2 w-0.5 rounded-full bg-white/80"
                style={{
                  animation: 'steam 2s ease-out infinite',
                  animationDelay: '0s',
                }}
              />
              <span
                className="h-3 w-0.5 rounded-full bg-white/60"
                style={{
                  animation: 'steam 2s ease-out infinite',
                  animationDelay: '0.5s',
                }}
              />
              <span
                className="h-2 w-0.5 rounded-full bg-white/80"
                style={{
                  animation: 'steam 2s ease-out infinite',
                  animationDelay: '1s',
                }}
              />
            </div>
          </div>
          <span>{t('coffee.buyMeACoffee')}</span>
        </button>
      )}

      {/* Modal */}
      {isOpen && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 p-4">
          <div className="relative w-full max-w-4xl rounded-2xl bg-white shadow-2xl overflow-hidden">
            {/* Close Button */}
            <button
              onClick={() => setIsOpen(false)}
              className="absolute right-4 top-4 z-10 rounded-full p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
            >
              <X className="h-5 w-5" />
            </button>

            <div className="flex flex-col lg:flex-row">
              {/* Left Side - QR Codes */}
              <div className="flex-1 p-6 lg:p-8 bg-gradient-to-br from-amber-50 to-orange-50">
                {/* Header */}
                <div className="mb-6 text-center">
                  <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-amber-100">
                    <svg
                      className="h-7 w-7 text-amber-600"
                      viewBox="0 0 24 24"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                    >
                      <path
                        d="M18 8H19C20.1046 8 21 8.89543 21 10C21 11.1046 20.1046 12 19 12H18V8Z"
                        fill="currentColor"
                        className="opacity-80"
                      />
                      <path
                        d="M2 8H18V14C18 16.2091 16.2091 18 14 18H6C3.79086 18 2 16.2091 2 14V8Z"
                        fill="currentColor"
                      />
                      <path
                        d="M5 20H15C15.5523 20 16 20.4477 16 21C16 21.5523 15.5523 22 15 22H5C4.44772 22 4 21.5523 4 21C4 20.4477 4.44772 20 5 20Z"
                        fill="currentColor"
                        className="opacity-60"
                      />
                    </svg>
                  </div>
                  <h3 className="text-xl font-bold text-gray-900">
                    {t('coffee.title')}
                  </h3>
                </div>

                {/* Message */}
                <p className="mb-6 text-center text-gray-600 text-sm leading-relaxed">
                  {t('coffee.message')}
                </p>

                {/* QR Codes */}
                <div className="grid grid-cols-2 gap-4">
                  {/* WeChat Pay */}
                  <div className="rounded-xl bg-white p-3 text-center shadow-sm">
                    <p className="mb-2 text-sm font-medium text-gray-700">
                      {t('coffee.wechatPay')}
                    </p>
                    <div className="overflow-hidden rounded-lg">
                      <img
                        src="/images/wechat-pay.jpg"
                        alt="WeChat Pay"
                        className="h-auto w-full object-contain"
                      />
                    </div>
                  </div>

                  {/* Alipay */}
                  <div className="rounded-xl bg-white p-3 text-center shadow-sm">
                    <p className="mb-2 text-sm font-medium text-gray-700">
                      {t('coffee.alipay')}
                    </p>
                    <div className="overflow-hidden rounded-lg">
                      <img
                        src="/images/alipay.jpg"
                        alt="Alipay"
                        className="h-auto w-full object-contain"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Side - Contact Info */}
              <div className="w-full lg:w-80 p-6 lg:p-8 bg-white border-l border-gray-100">
                <h4 className="text-lg font-bold text-gray-900 mb-6 flex items-center gap-2">
                  <span className="w-1 h-6 bg-amber-500 rounded-full"></span>
                  {t('coffee.contactMe')}
                </h4>

                <div className="space-y-4">
                  {contacts.map((contact) => (
                    <a
                      key={contact.name}
                      href={contact.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex items-start gap-3 p-3 rounded-xl transition-all hover:bg-gray-50"
                    >
                      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${contact.color} text-white shadow-md group-hover:shadow-lg transition-shadow`}>
                        <contact.icon className="h-5 w-5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-900">
                          {contact.name}
                        </p>
                        <p className="text-xs text-gray-500 truncate">
                          {contact.value}
                        </p>
                      </div>
                    </a>
                  ))}
                </div>

                {/* Thank You Message */}
                <div className="mt-8 pt-6 border-t border-gray-100">
                  <p className="text-center text-sm text-gray-400">
                    {t('coffee.thankYou')}
                  </p>
                  <div className="mt-3 flex justify-center gap-1">
                    <span className="text-amber-400">★</span>
                    <span className="text-amber-400">★</span>
                    <span className="text-amber-400">★</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Steam Animation Styles */}
      <style>{`
        @keyframes steam {
          0% {
            transform: translateY(0) scaleY(1);
            opacity: 0.8;
          }
          50% {
            opacity: 0.4;
          }
          100% {
            transform: translateY(-8px) scaleY(0.5);
            opacity: 0;
          }
        }
      `}</style>
    </>
  );
}
