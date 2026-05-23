#!/usr/bin/env python3
"""Unit tests for email classification safeguards (no API calls)."""

import unittest

from email_agent import (
    MOCK_EMAILS,
    apply_classification_safeguards,
    looks_like_clear_promotion,
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


class TestPromotionDetection(unittest.TestCase):
    def test_flash_sale_is_promotion(self):
        self.assertTrue(looks_like_clear_promotion(MOCK_EMAILS[0]))

    def test_personal_test_email_is_not_promotion(self):
        self.assertFalse(looks_like_clear_promotion(MOCK_EMAILS[3]))


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


if __name__ == '__main__':
    unittest.main()
