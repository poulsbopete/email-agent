#!/usr/bin/env python3
"""Unit tests for email classification safeguards (no API calls)."""

import os
import unittest
import unittest.mock

from email_agent import (
    MOCK_EMAILS,
    apply_classification_safeguards,
    build_voice_prompt_section,
    has_list_unsubscribe,
    is_no_reply_sender,
    looks_like_clear_promotion,
    load_email_sender_name,
    load_email_voice,
    load_voice_examples,
    requests_response,
)


class TestResponseRequestDetection(unittest.TestCase):
    def test_please_respond_phrase(self):
        email = MOCK_EMAILS[3]
        self.assertTrue(requests_response(email))

    def test_question_in_subject(self):
        email = {
            'subject': 'Are you free tomorrow?',
            'body': 'Just checking.',
            'full_body': 'Just checking.',
        }
        self.assertTrue(requests_response(email))

    def test_promo_does_not_request_response(self):
        email = MOCK_EMAILS[0]
        self.assertFalse(requests_response(email))

    def test_promo_question_subject_does_not_request_response(self):
        email = {
            'from': 'no-reply@store.example.com',
            'subject': 'Hungry for summer?',
            'body': 'Shop our seasonal favorites today.',
            'full_body': 'Shop our seasonal favorites today.',
        }
        self.assertFalse(requests_response(email))


class TestPromotionDetection(unittest.TestCase):
    def test_flash_sale_is_promotion(self):
        self.assertTrue(looks_like_clear_promotion(MOCK_EMAILS[0]))

    def test_personal_test_email_is_not_promotion(self):
        self.assertFalse(looks_like_clear_promotion(MOCK_EMAILS[3]))

    def test_cvs_extracare_sale_subject(self):
        email = {
            'from': 'CVS ExtraCare <extracare@e.cvs.com>',
            'subject': 'Your The Villages Store Has Special Sale Prices!',
            'body': 'Save on essentials this week. View deals in store.',
            'full_body': 'Save on essentials this week. View deals in store.',
        }
        self.assertTrue(looks_like_clear_promotion(email))

    def test_no_reply_sender_is_promotion(self):
        email = {
            'from': 'Brand <no-reply@brand.example.com>',
            'subject': 'Hungry for summer?',
            'body': 'Try our new menu items.',
            'full_body': 'Try our new menu items.',
        }
        self.assertTrue(is_no_reply_sender(email))
        self.assertTrue(looks_like_clear_promotion(email))

    def test_list_unsubscribe_header_is_promotion(self):
        email = {
            'from': 'news@retailer.com',
            'subject': 'Weekly picks for you',
            'body': 'Check out these items.',
            'full_body': 'Check out these items.',
            'list_unsubscribe': '<mailto:unsub@retailer.com>, <https://retailer.com/unsub>',
        }
        self.assertTrue(has_list_unsubscribe(email))
        self.assertTrue(looks_like_clear_promotion(email))


class TestArchiveSafeguards(unittest.TestCase):
    def test_blocks_archive_for_response_request(self):
        email = MOCK_EMAILS[3]
        analysis = {
            'action': 'archive',
            'email_type': 'promotion',
            'reason': 'Misclassified as marketing',
        }
        result = apply_classification_safeguards(email, analysis)
        self.assertNotEqual(result['action'], 'archive')
        self.assertIn(result['action'], ('respond', 'needs_user_input'))

    def test_response_request_overrides_to_respond(self):
        email = MOCK_EMAILS[3]
        analysis = {'action': 'archive', 'email_type': 'promotion', 'reason': 'test'}
        result = apply_classification_safeguards(email, analysis)
        self.assertEqual(result['action'], 'respond')
        self.assertTrue(result.get('suggested_response'))

    def test_own_address_overrides_to_needs_user_input(self):
        email = {
            'from': 'me@gmail.com',
            'subject': 'Note to self',
            'body': 'Reminder for later',
            'full_body': 'Reminder for later',
        }
        analysis = {'action': 'archive', 'email_type': 'promotion', 'reason': 'test'}
        result = apply_classification_safeguards(
            email, analysis, own_email='me@gmail.com',
        )
        self.assertEqual(result['action'], 'needs_user_input')

    def test_ambiguous_archive_becomes_needs_user_input(self):
        email = {
            'from': 'vendor@example.com',
            'subject': 'Contract terms follow-up',
            'body': 'Can we discuss the liability clause before signing?',
            'full_body': 'Can we discuss the liability clause before signing?',
        }
        analysis = {'action': 'archive', 'email_type': 'promotion', 'reason': 'test'}
        result = apply_classification_safeguards(email, analysis)
        self.assertEqual(result['action'], 'needs_user_input')

    def test_clear_promotion_still_archives(self):
        email = MOCK_EMAILS[0]
        analysis = {'action': 'archive', 'email_type': 'promotion', 'reason': 'sale email'}
        result = apply_classification_safeguards(email, analysis)
        self.assertEqual(result['action'], 'archive')

    def test_personal_sender_overrides_archive(self):
        email = MOCK_EMAILS[1]
        analysis = {'action': 'archive', 'email_type': 'promotion', 'reason': 'test'}
        result = apply_classification_safeguards(
            email, analysis, personal_senders={'friend@example.com'},
        )
        self.assertEqual(result['action'], 'respond')


class TestRespondSafeguards(unittest.TestCase):
    def test_respond_overridden_to_archive_for_cvs_promo(self):
        email = {
            'from': 'CVS ExtraCare <extracare@e.cvs.com>',
            'subject': 'Your The Villages Store Has Special Sale Prices!',
            'body': 'Save on essentials this week.',
            'full_body': 'Save on essentials this week.',
        }
        analysis = {
            'action': 'respond',
            'email_type': 'general',
            'suggested_response': 'Got your message — thanks for reaching out!',
            'reason': 'Misclassified as personal',
        }
        result = apply_classification_safeguards(email, analysis)
        self.assertEqual(result['action'], 'archive')
        self.assertIsNone(result.get('suggested_response'))

    def test_respond_overridden_to_archive_for_no_reply(self):
        email = {
            'from': 'Brand <no-reply@brand.example.com>',
            'subject': 'Hungry for summer?',
            'body': 'Try our new menu items.',
            'full_body': 'Try our new menu items.',
        }
        analysis = {
            'action': 'respond',
            'email_type': 'general',
            'suggested_response': 'Got your message — thanks for reaching out!',
            'reason': 'Question in subject',
        }
        result = apply_classification_safeguards(email, analysis)
        self.assertEqual(result['action'], 'archive')

    def test_respond_overridden_to_archive_for_list_unsubscribe(self):
        email = {
            'from': 'news@retailer.com',
            'subject': 'Weekly picks for you',
            'body': 'Check out these items.',
            'full_body': 'Check out these items.',
            'list_unsubscribe': '<mailto:unsub@retailer.com>',
        }
        analysis = {'action': 'respond', 'email_type': 'general', 'reason': 'test'}
        result = apply_classification_safeguards(email, analysis)
        self.assertEqual(result['action'], 'archive')

    def test_promo_with_question_still_archives_when_claude_says_archive(self):
        email = {
            'from': 'no-reply@store.example.com',
            'subject': 'Hungry for summer?',
            'body': 'Limited time offer. Shop now.',
            'full_body': 'Limited time offer. Shop now.',
        }
        analysis = {'action': 'archive', 'email_type': 'promotion', 'reason': 'sale email'}
        result = apply_classification_safeguards(email, analysis)
        self.assertEqual(result['action'], 'archive')

    def test_personal_sender_still_gets_respond_not_archive(self):
        email = {
            'from': 'friend@example.com',
            'subject': '50% off my couch — want it?',
            'body': 'Moving sale, let me know if you want the couch.',
            'full_body': 'Moving sale, let me know if you want the couch.',
        }
        analysis = {'action': 'archive', 'email_type': 'promotion', 'reason': 'test'}
        result = apply_classification_safeguards(
            email, analysis, personal_senders={'friend@example.com'},
        )
        self.assertEqual(result['action'], 'respond')


class TestEmailVoice(unittest.TestCase):
    def test_voice_prompt_empty_when_unset(self):
        with unittest.mock.patch.dict('os.environ', {}, clear=True):
            self.assertEqual(build_voice_prompt_section(), '')

    def test_voice_prompt_includes_name_and_voice(self):
        env = {
            'EMAIL_SENDER_NAME': 'Peter Simkins',
            'EMAIL_VOICE': 'Direct and friendly.',
        }
        with unittest.mock.patch.dict('os.environ', env, clear=True):
            section = build_voice_prompt_section()
            self.assertIn('Peter Simkins', section)
            self.assertIn('Direct and friendly.', section)
            self.assertEqual(load_email_sender_name(), 'Peter Simkins')
            self.assertEqual(load_email_voice(), 'Direct and friendly.')

    def test_voice_prompt_includes_examples_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as tmp:
            tmp.write('# comment\nThanks for the note.\nBest,\nPeter\n')
            path = tmp.name
        try:
            env = {'VOICE_EXAMPLES_FILE': path}
            with unittest.mock.patch.dict('os.environ', env, clear=True):
                section = build_voice_prompt_section()
                self.assertIn('Thanks for the note.', section)
                self.assertNotIn('# comment', section)
                self.assertEqual(load_voice_examples(), 'Thanks for the note.\nBest,\nPeter')
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
