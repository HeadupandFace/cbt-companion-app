document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements ---
    const chatMessages = document.getElementById('chatMessages');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');
    const messageArea = document.getElementById('messageArea');

    // --- Crisis Modal Elements ---
    const crisisModal = document.getElementById('crisis-alert-modal');
    const crisisModalMessage = document.getElementById('crisis-modal-message');
    const crisisContactsList = document.getElementById('crisis-contacts-list');
    const closeCrisisModalBtn = document.getElementById('close-crisis-modal-btn');

    // --- ADDED: Web Speech API for voice output ---
    const synth = window.speechSynthesis;

    // --- ADDED: Function to speak text, handles newlines ---
    function speakText(text) {
        if (synth.speaking) {
            // Optional: stop any previous speech before starting new
            synth.cancel(); 
        }
        if (text !== '') {
            // Clean the text for speech: replace all newline characters (\n) with a space
            const textForSpeech = text.replace(/\n/g, ' ');

            const utterance = new SpeechSynthesisUtterance(textForSpeech);
            
            utterance.onerror = function(event) {
                console.error('SpeechSynthesisUtterance.onerror', event.error);
            };

            // You can configure voice, pitch, rate here if needed
            // e.g., const voices = synth.getVoices();
            // utterance.voice = voices.find(v => v.name === 'Google UK English Female');

            synth.speak(utterance);
        }
    }


    // --- Helper function for displaying general status messages ---
    function displayStatusMessage(message, type = 'info') {
        if (!messageArea) return;
        messageArea.textContent = message;
        messageArea.classList.remove('hidden');
        setTimeout(() => messageArea.classList.add('hidden'), 5000);
    }

    // --- Functions to handle the crisis modal ---
    function displayCrisisModal(data) {
        if (!crisisModal) return;
        crisisModalMessage.textContent = data.ai_response;
        crisisContactsList.innerHTML = '';
        if (data.support_contacts) {
            for (const key in data.support_contacts) {
                if (key.endsWith('_title')) {
                    const serviceName = data.support_contacts[key];
                    const phoneKey = key.replace('_title', '_phone');
                    const phoneNumber = data.support_contacts[phoneKey];
                    
                    const listItem = document.createElement('li');
                    listItem.className = "text-gray-700 dark:text-gray-200";
                    listItem.innerHTML = `<span class="font-semibold">${serviceName}:</span> <a href="tel:${phoneNumber}" class="font-bold text-red-600 dark:text-red-400 hover:underline">${phoneNumber}</a>`;
                    crisisContactsList.appendChild(listItem);
                }
            }
        }
        crisisModal.classList.remove('hidden');
    }

    function hideCrisisModal() {
        if (!crisisModal) return;
        crisisModal.classList.add('hidden');
    }

    if (closeCrisisModalBtn) {
        closeCrisisModalBtn.addEventListener('click', hideCrisisModal);
    }
    
    // --- Main Chat Message Sending Logic ---
    async function sendMessage() {
        const messageText = userInput.value.trim();
        if (!messageText) {
            displayStatusMessage('Please type a message to send.', 'warning');
            return;
        }

        addChatMessage('user', messageText);
        userInput.value = '';
        
        addChatMessage('assistant', '...', true);

        try {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ message: messageText })
            });

            removeThinkingIndicator();

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'An unknown error occurred.');
            }

            const data = await response.json();

            if (data.crisis_alert) {
                displayCrisisModal(data);
                // We also speak the crisis alert message
                speakText(data.ai_response);
            } else {
                addChatMessage('assistant', data.ai_response);
                // --- CHANGED: Call the new speakText function for normal responses ---
                speakText(data.ai_response);
            }

        } catch (error) {
            console.error('Chat API Error:', error);
            removeThinkingIndicator();
            const errorMessage = `Sorry, I encountered an error: ${error.message}`;
            addChatMessage('assistant', errorMessage);
            speakText(errorMessage); // Speak the error message
        }
    }

    if (sendBtn) {
        sendBtn.addEventListener('click', sendMessage);
    }

    if (userInput) {
        userInput.addEventListener('keypress', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            }
        });
    }

    // --- Helper functions for adding/removing chat messages ---
    function addChatMessage(sender, text, isThinking = false) {
        const messageDiv = document.createElement('div');
        
        const senderClass = sender === 'user' 
            ? 'bg-indigo-100 dark:bg-indigo-700 text-gray-900 dark:text-gray-100 ml-auto' 
            : 'bg-gray-200 dark:bg-gray-600 text-gray-900 dark:text-gray-100 mr-auto';

        messageDiv.className = `p-3 rounded-lg max-w-[80%] mb-2 ${senderClass}`;
        
        if (isThinking) {
            messageDiv.id = 'thinking-indicator';
            messageDiv.innerHTML = `<div class="flex items-center space-x-2"><div class="w-2 h-2 bg-gray-500 rounded-full animate-pulse"></div><div class="w-2 h-2 bg-gray-500 rounded-full animate-pulse" style="animation-delay: 0.2s;"></div><div class="w-2 h-2 bg-gray-500 rounded-full animate-pulse" style="animation-delay: 0.4s;"></div></div>`;
        } else {
            const formattedText = text.replace(/\n/g, '<br>');
            messageDiv.innerHTML = formattedText;
        }

        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function removeThinkingIndicator() {
        const indicator = document.getElementById('thinking-indicator');
        if (indicator) {
            indicator.remove();
        }
    }
});